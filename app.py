"""
vfat-tracker — standalone service.
Tracks vfat/Sickle-held Uniswap-V3-shaped positions for a wallet,
across multiple chains and protocols (see vfat_adapter.CHAINS).

Base: Uniswap V3 and PancakeSwap V3, both confirmed direct-hold (no
gauge staking), discovered dynamically via Alchemy's indexed API.
Optimism: Uniswap V3 only, using a known Sickle address + known
tokenIds rather than discovery — no reliable discovery mechanism
exists there (see vfat_adapter.py's OPTIMISM_* comments for why).
Aerodrome Slipstream (gauge-staked, confirmed via a real harvestFor
tx) is not yet built.
"""

import os
import time
import base64
import logging
import threading
import json
import fcntl

import requests
from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from web3 import Web3
from dotenv import load_dotenv

import vfat_adapter as va

load_dotenv()

app = Flask(__name__, static_folder="static")
CORS(app)
logging.basicConfig(level=logging.INFO)

# ── Basic Auth (optional — same pattern as the other trackers) ─────────────
_PASSWORD = os.environ.get("PASSWORD", "")


@app.before_request
def require_auth():
    if not _PASSWORD:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            _, pw = base64.b64decode(auth[6:]).decode().split(":", 1)
            if pw == _PASSWORD:
                return
        except Exception:
            pass
    return Response("Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="vfat Tracker"'})


# ── RPC setup ─────────────────────────────────────────────────────────────
ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
DEFAULT_WALLET = os.environ.get("DEFAULT_WALLET", "").strip()

# Optimism has no Alchemy access (not configured for this key), so it
# uses free public RPC endpoints instead — with a fallback, since these
# proved less reliable than Alchemy (the same eth_getLogs call
# succeeded once and failed minutes later with a different error, on
# the same endpoint, discovered while testing Optimism directly).
OPTIMISM_RPC_URLS = [
    os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io"),
    os.environ.get("OPTIMISM_RPC_FALLBACK", "https://optimism.drpc.org"),
]

_w3_cache = {}


def get_w3(chain: str = "base"):
    if chain in _w3_cache:
        return _w3_cache[chain]

    if chain == "base":
        if not ALCHEMY_BASE:
            return None
        w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    elif chain == "mainnet":
        # Same Alchemy key as Base, different subdomain — confirmed
        # working directly (debug_alchemy_eth.py), not assumed.
        if not ALCHEMY_BASE or "base-mainnet" not in ALCHEMY_BASE:
            return None
        eth_url = ALCHEMY_BASE.replace("base-mainnet", "eth-mainnet")
        w3 = Web3(Web3.HTTPProvider(eth_url))
    elif chain == "optimism":
        w3 = None
        for url in OPTIMISM_RPC_URLS:
            candidate = Web3(Web3.HTTPProvider(url))
            if candidate.is_connected():
                w3 = candidate
                break
        if w3 is None:
            return None
    else:
        return None

    _w3_cache[chain] = w3
    return w3


# ── Cache ────────────────────────────────────────────────────────────────
_cache = {}
_stale_cache = {}
CACHE_TTL = 120

# ── Token price lookup (GeckoTerminal free/keyless API) ────────────────────
_GECKOTERMINAL_TOKEN_PRICE_URL = "https://api.geckoterminal.com/api/v2/simple/networks/{}/token_price/{}"


def get_token_prices_usd(addresses: list, gecko_network: str = "base") -> dict:
    if not addresses:
        return {}
    unique = sorted(set(a.lower() for a in addresses))
    url = _GECKOTERMINAL_TOKEN_PRICE_URL.format(gecko_network, ",".join(unique))
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        token_prices = data.get("data", {}).get("attributes", {}).get("token_prices", {})
        return {addr.lower(): float(price) for addr, price in token_prices.items()}
    except Exception as e:
        app.logger.warning("GeckoTerminal price fetch failed (%s): %s", gecko_network, e)
        return {}


# ── Pool trading volume (GeckoTerminal OHLCV, by pool address) ─────────────
_GECKOTERMINAL_OHLCV_URL = "https://api.geckoterminal.com/api/v2/networks/{}/pools/{}/ohlcv/day"
_POOL_VOLUME_CACHE = {}
_POOL_VOLUME_CACHE_TTL = 1800
_VOLUME_RANGE_DAYS = {"7d": 7, "30d": 30, "60d": 60, "90d": 90, "180d": 180}


def get_pool_volume_usd(pool_address: str, days: int, gecko_network: str = "base") -> list:
    cache_key = f"{gecko_network}:{pool_address.lower()}:{days}"
    cached = _POOL_VOLUME_CACHE.get(cache_key)
    if cached and time.time() - cached["fetched_at"] < _POOL_VOLUME_CACHE_TTL:
        return cached["candles"]
    url = _GECKOTERMINAL_OHLCV_URL.format(gecko_network, pool_address)
    resp = requests.get(url, params={"aggregate": 1, "limit": days, "currency": "usd"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    ohlcv_list = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
    candles = sorted(
        ({"ts": row[0], "volume_usd": row[5]} for row in ohlcv_list),
        key=lambda c: c["ts"],
    )
    _POOL_VOLUME_CACHE[cache_key] = {"candles": candles, "fetched_at": time.time()}
    return candles


# ── History storage (portfolio-level and per-position) ─────────────────────
def _history_file_path(name: str) -> str:
    return os.path.join(HISTORY_DIR, f"history_{name}.json")


def _closed_positions_file_path() -> str:
    return os.path.join(HISTORY_DIR, "closed_positions.json")


def append_history_snapshot(name: str, snapshot: dict):
    path = _history_file_path(name)
    with _history_lock:
        history = _read_json_locked(path, [])
        history.append(snapshot)
        _write_json_locked(path, history)


def load_history(name: str) -> list:
    return _read_json_locked(_history_file_path(name), [])


# ── Persistent baseline tracking (Railway volume) ───────────────────────────
# Needed for P&L (no cost-basis data exists on-chain for a raw Uniswap V3
# NFT — same "since we started tracking" approach as snuggle-tracker) and
# for a fees-earned-over-time APR (the NPM has no cumulative-fees counter;
# tokensOwed resets to 0 on every collect(), so "lifetime fees" isn't
# available the way it was for Snuggle's vault struct).
HISTORY_DIR = os.environ.get("HISTORY_DIR", "/data")
_history_lock = threading.Lock()
SNAPSHOT_INTERVAL = 3600  # 1 hour


def _known_positions_file_path() -> str:
    return os.path.join(HISTORY_DIR, "known_positions.json")


def _read_json_locked(path: str, default):
    try:
        with open(path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json_locked(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def fetch_all_positions(wallet: str):
    """Loops every chain in va.CHAINS, and within each chain every
    protocol, fetching whatever's currently open. Positions come back
    tagged with 'chain' and 'protocol' so callers/UI can distinguish
    them (and so history/baseline keys stay unique across chains and
    protocols, since token IDs are only unique per-contract).

    Discovery is per-PROTOCOL, not per-chain — Base mixes 'dynamic'
    protocols (Uniswap, Pancake: direct-hold, discovered via Alchemy)
    with Aerodrome's 'known_exists_only' (ownership genuinely varies —
    checked directly: one known position is held by the Sickle itself,
    the other by an actual gauge — so no single expected owner to
    verify against, just existence). Optimism/mainnet use
    'known_owner_check' (a fixed known Sickle, no factory available).

    Caveat: for 'known_*' protocols, the supplied wallet is NOT used to
    find the position — there's no reliable discovery for these, so
    they always report their hardcoded known tokenIds regardless of
    which wallet was queried. Only matters if this app is ever pointed
    at a wallet other than DEFAULT_WALLET, which isn't the current use
    case.

    Returns ({"base": sickle_address_or_None, ...}, positions)."""
    all_positions = []
    sickle_addresses = {}

    for chain_key, chain_cfg in va.CHAINS.items():
        w3 = get_w3(chain_key)
        if w3 is None:
            sickle_addresses[chain_key] = None
            continue

        if chain_cfg["sickle_resolution"] == "dynamic":
            sickle_address = va.resolve_sickle(w3, wallet)
        else:
            sickle_address = chain_cfg["fixed_sickle_address"]
        sickle_addresses[chain_key] = sickle_address

        for protocol_key, cfg in chain_cfg["protocols"].items():
            discovery = cfg["discovery"]

            if discovery == "dynamic":
                if sickle_address is None:
                    continue
                token_ids = va.discover_current_token_ids(w3, sickle_address, cfg["npm"])
            elif discovery == "known_owner_check":
                token_ids = va.check_known_token_ids(w3, cfg["expected_owner"], cfg["npm"], cfg["known_token_ids"])
            elif discovery == "known_exists_only":
                token_ids = va.check_known_token_ids_exists_only(w3, cfg["npm"], cfg["known_token_ids"])
            else:
                raise ValueError(f"Unknown discovery mode: {discovery}")

            for tid in token_ids:
                # Aerodrome's fetch_fn needs the resolved Sickle address
                # to tell staked-vs-unstaked apart and query the right
                # gauge for AERO rewards — every other protocol's
                # fetch_fn ignores an extra kwarg it doesn't declare,
                # so this stays a special case rather than a shared
                # convention that would confuse the simpler protocols.
                if protocol_key == "aerodrome":
                    p = cfg["fetch_fn"](w3, tid, sickle_address=sickle_address)
                else:
                    p = cfg["fetch_fn"](w3, tid)
                p["chain"] = chain_key
                p["chain_label"] = chain_cfg["label"]
                p["protocol"] = protocol_key
                p["protocol_label"] = cfg["label"]
                all_positions.append(p)

    return sickle_addresses, all_positions


def capture_snapshot():
    """Runs hourly. Records a baseline (value + uncollected-fees, both
    USD) for any position that doesn't have one yet — self-healing: a
    brand-new position AND a position that predates this feature both
    just get baselined at whatever their state is on the next cycle
    that sees them. Never overwrites an existing baseline."""
    if not DEFAULT_WALLET:
        return
    try:
        sickle_addresses, positions = fetch_all_positions(DEFAULT_WALLET)
        positions = enrich_with_usd(positions)
    except Exception as e:
        app.logger.warning("Snapshot capture failed: %s", e)
        return

    # Key by chain:protocol:token_id — token IDs are sequential
    # per-contract, so the same numeric ID can exist independently on
    # Base's Uniswap NPM, Base's Pancake NPM, and Optimism's Uniswap
    # NPM. Not namespacing this would silently conflate unrelated
    # positions across chains as well as across protocols.
    now = time.time()
    with _history_lock:
        known = _read_json_locked(_known_positions_file_path(), {})
        current_keys = {f"{p['chain']}:{p['protocol']}:{p['token_id']}" for p in positions}
        closed_now = [k for k in known if k not in current_keys]

        if closed_now:
            closed_list = _read_json_locked(_closed_positions_file_path(), [])
            for key in closed_now:
                last_known = known[key]
                closed_list.append({
                    "key": key,
                    "pool": last_known.get("pool"),
                    "chain": last_known.get("chain"),
                    "protocol": last_known.get("protocol"),
                    "closed_at": now,
                    "last_value_usd": last_known.get("last_value_usd"),
                })
                _append_closed_marker(key, now)
            _write_json_locked(_closed_positions_file_path(), closed_list)

        for p in positions:
            key = f"{p['chain']}:{p['protocol']}:{p['token_id']}"
            prior = known.get(key, {})
            baseline_value_usd = prior.get("baseline_value_usd")
            baseline_fees_usd = prior.get("baseline_fees_usd")
            baseline_ts = prior.get("baseline_ts")

            # A deposit or withdrawal on an existing position (rebalance,
            # increase/decrease liquidity) changes on-chain liquidity —
            # detected exactly, since it's a uint128, not a float. Without
            # this, added capital reads as a huge fake "gain" (value jumps
            # but baseline doesn't), and a withdrawal reads as a fake
            # "loss" the same way. Reset the baseline when it happens —
            # P&L becomes "since this capital level," not true lifetime
            # cash-flow-adjusted P&L, but that's a much smaller gap than
            # miscounting your own deposits as returns.
            prior_liquidity = prior.get("last_liquidity")
            liquidity_changed = prior_liquidity is not None and p["liquidity"] != prior_liquidity

            if (baseline_value_usd is None or liquidity_changed) and p["position_value_usd"] is not None:
                baseline_value_usd = p["position_value_usd"]
                baseline_fees_usd = p["uncollected_fees_usd"] or 0.0
                baseline_ts = now
            known[key] = {
                "chain": p["chain"],
                "protocol": p["protocol"],
                "token_id": p["token_id"],
                "pool": f"{p['token0']['symbol']}/{p['token1']['symbol']}",
                "pool_address": p["pool_address"],
                "last_liquidity": p["liquidity"],
                "baseline_value_usd": baseline_value_usd,
                "baseline_fees_usd": baseline_fees_usd,
                "baseline_ts": baseline_ts,
                "last_value_usd": p["position_value_usd"],
                "last_seen": now,
            }
        _write_json_locked(_known_positions_file_path(), known)

    # Portfolio-level history.
    portfolio = compute_portfolio_summary(positions)
    append_history_snapshot("portfolio", {
        "ts": now,
        "total_value_usd": portfolio["total_value_usd"],
        "total_fees_usd": portfolio["total_fees_usd"],
        "position_count": portfolio["position_count"],
        "out_of_range_count": portfolio["out_of_range_count"],
    })

    # Per-position history.
    for p in positions:
        key = f"{p['chain']}:{p['protocol']}:{p['token_id']}"
        append_history_snapshot(f"pos_{key}", {
            "ts": now,
            "value_usd": p["position_value_usd"],
            "fees_usd": p["uncollected_fees_usd"],
            "in_range": p["in_range"],
        })


def _append_closed_marker(key: str, ts: float):
    """Final marker in a closed position's own history file, so its
    chart visibly shows where it ends. Caller already holds _history_lock."""
    path = _history_file_path(f"pos_{key}")
    history = _read_json_locked(path, [])
    history.append({"ts": ts, "key": key, "closed": True})
    _write_json_locked(path, history)


def _snapshot_loop():
    while True:
        try:
            capture_snapshot()
        except Exception as e:
            app.logger.error("Snapshot loop error: %s", e)
        time.sleep(SNAPSHOT_INTERVAL)


def enrich_with_usd(positions: list) -> list:
    """Adds USD values and range-bar-support fields. Fields are None
    where price data wasn't available — never fabricated.

    Prices are looked up per-chain (grouped, not all together) — a
    token address on Optimism is a different contract than the same
    symbol on Base, and GeckoTerminal scopes its token_price lookup by
    network. Querying everything under one network would silently
    return no price for the other chain's tokens rather than a wrong
    one, but "silently missing" for an entire chain isn't much better —
    worth doing properly."""
    positions_by_chain = {}
    for p in positions:
        positions_by_chain.setdefault(p["chain"], []).append(p)

    prices = {}
    for chain_key, chain_positions in positions_by_chain.items():
        gecko_network = va.CHAINS[chain_key]["gecko_network"]
        addresses = []
        for p in chain_positions:
            addresses.append(p["token0"]["address"])
            addresses.append(p["token1"]["address"])
            if p.get("reward_token_address"):
                addresses.append(p["reward_token_address"])
        prices.update(get_token_prices_usd(addresses, gecko_network))

    for p in positions:
        price0 = prices.get(p["token0"]["address"].lower())
        price1 = prices.get(p["token1"]["address"].lower())

        position_value_usd = None
        if price0 is not None and price1 is not None:
            position_value_usd = p["amount0"] * price0 + p["amount1"] * price1
        p["position_value_usd"] = position_value_usd

        fees_usd = None
        if price0 is not None and price1 is not None:
            fees_usd = p["uncollected_fees0"] * price0 + p["uncollected_fees1"] * price1
        p["uncollected_fees_usd"] = fees_usd

        pending_reward_usd = None
        if p.get("pending_reward") is not None and p.get("reward_token_address"):
            reward_price = prices.get(p["reward_token_address"].lower())
            if reward_price is not None:
                pending_reward_usd = p["pending_reward"] * reward_price
        p["pending_reward_usd"] = pending_reward_usd

        # Range-bar support fields, same convention as the other trackers.
        cp, pl, pu = p.get("current_price"), p.get("price_lower"), p.get("price_upper")
        pct_from_lower = pct_from_upper = None
        if cp and pl is not None and pu is not None and cp > 0:
            pct_from_lower = (cp - pl) / cp * 100.0
            pct_from_upper = (pu - cp) / cp * 100.0
        p["pct_from_lower"] = pct_from_lower
        p["pct_from_upper"] = pct_from_upper

        if pl and pu and pl > 0:
            p["range_width_pct"] = (pu - pl) / pl * 100.0
        else:
            p["range_width_pct"] = None

    return positions


def compute_portfolio_summary(positions: list) -> dict:
    total_value_usd = sum(p["position_value_usd"] for p in positions if p["position_value_usd"] is not None)
    total_fees_usd = sum(p["uncollected_fees_usd"] for p in positions if p["uncollected_fees_usd"] is not None)
    pnl_positions = [p for p in positions if p.get("pnl_usd") is not None]
    total_pnl_usd = sum(p["pnl_usd"] for p in pnl_positions) if pnl_positions else None
    return {
        "total_value_usd": total_value_usd if total_value_usd > 0 else None,
        "total_fees_usd": total_fees_usd if total_fees_usd > 0 else None,
        "total_pnl_usd": total_pnl_usd,
        "position_count": len(positions),
        "out_of_range_count": sum(1 for p in positions if not p["in_range"]),
    }


def attach_pnl_and_apr(positions: list) -> list:
    """Read-only — the background snapshot loop is the sole writer of
    known_positions.json, avoiding two code paths racing on the same
    file. A position with no recorded baseline yet (brand new, next
    snapshot cycle hasn't run) gets None, never a fabricated number.

    APR here is "fees earned since we started tracking, annualized" —
    NOT true lifetime APR (no cumulative-fee counter exists on-chain
    for a raw Uniswap V3 NFT the way Snuggle's vault provided one).
    Forced to 0 whenever the position is currently out of range,
    regardless of what it earned earlier in the tracked window, since
    an out-of-range position earns zero trading fees right now — a
    stale nonzero APR from before it left the range would be
    misleading about its current state.

    One known limitation: if fees were manually collected during the
    tracked window, uncollected_fees_usd drops and this would compute
    a negative "fees earned" — clamped to 0 rather than shown negative,
    since a negative APR from a collect() is more confusing than
    informative. That does mean a just-collected position under-reports
    its true earnings for that window."""
    known = _read_json_locked(_known_positions_file_path(), {})
    now = time.time()
    for p in positions:
        key = f"{p['chain']}:{p['protocol']}:{p['token_id']}"
        entry = known.get(key)
        baseline_value = entry.get("baseline_value_usd") if entry else None
        baseline_fees = entry.get("baseline_fees_usd") if entry else None
        baseline_ts = entry.get("baseline_ts") if entry else None

        pnl_usd = pnl_pct = apr_pct = None
        if baseline_value is not None and baseline_value > 0 and p["position_value_usd"] is not None:
            pnl_usd = p["position_value_usd"] - baseline_value
            pnl_pct = pnl_usd / baseline_value * 100.0

        if (not p["in_range"]):
            apr_pct = 0.0
        elif (baseline_fees is not None and baseline_ts is not None
                and p["uncollected_fees_usd"] is not None and p["position_value_usd"]):
            days_tracked = (now - baseline_ts) / 86400.0
            fees_earned = max(0.0, p["uncollected_fees_usd"] - baseline_fees)
            if days_tracked > 0.5 and p["position_value_usd"] > 0:
                apr_pct = fees_earned / p["position_value_usd"] * (365.0 / days_tracked) * 100.0

        p["baseline_value_usd"] = baseline_value
        p["pnl_usd"] = pnl_usd
        p["pnl_pct"] = pnl_pct
        p["apr_pct"] = apr_pct
    return positions


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/positions")
def api_positions():
    wallet = request.args.get("wallet", "").strip() or DEFAULT_WALLET
    if not wallet:
        return jsonify({"error": "No wallet specified and no default wallet configured"}), 400
    if not wallet.startswith("0x") or len(wallet) != 42:
        return jsonify({"error": "Invalid wallet address"}), 400

    cache_key = f"positions:{wallet.lower()}"
    bust = request.args.get("bust", "0") == "1"
    cached = _cache.get(cache_key)
    if not bust and cached and time.time() - cached["fetched_at"] < CACHE_TTL:
        return jsonify({**cached, "cached": True})

    try:
        sickle_addresses, positions = fetch_all_positions(wallet)
        positions = enrich_with_usd(positions)
        positions = attach_pnl_and_apr(positions)
    except Exception as e:
        app.logger.error("Position fetch failed for %s: %s", wallet, e)
        stale = _stale_cache.get(cache_key)
        if stale:
            app.logger.warning("Serving stale data for %s", wallet)
            return jsonify({**stale, "cached": True, "stale": True})
        return jsonify({"error": str(e)}), 500

    portfolio = compute_portfolio_summary(positions)
    result = {
        "sickle_addresses": sickle_addresses,
        "positions": positions,
        "portfolio": portfolio,
        "fetched_at": time.time(),
    }
    _cache[cache_key] = result
    _stale_cache[cache_key] = result
    return jsonify({**result, "cached": False})


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "rpc_configured": bool(ALCHEMY_BASE)})


_RANGE_TO_SECONDS = {"7d": 7 * 86400, "30d": 30 * 86400, "90d": 90 * 86400, "all": None}


@app.route("/api/history")
def api_history():
    range_key = request.args.get("range", "30d")
    if range_key not in _RANGE_TO_SECONDS:
        return jsonify({"error": "range must be one of: 7d, 30d, 90d, all"}), 400
    history = load_history("portfolio")
    window_seconds = _RANGE_TO_SECONDS[range_key]
    if window_seconds is not None:
        cutoff = time.time() - window_seconds
        history = [s for s in history if s["ts"] >= cutoff]
    return jsonify({"snapshots": history, "range": range_key})


@app.route("/api/history/<int:token_id>")
def api_position_history(token_id):
    range_key = request.args.get("range", "30d")
    protocol = request.args.get("protocol", "uniswap")
    chain = request.args.get("chain", "base")
    if range_key not in _RANGE_TO_SECONDS:
        return jsonify({"error": "range must be one of: 7d, 30d, 90d, all"}), 400
    if chain not in va.CHAINS:
        return jsonify({"error": f"chain must be one of: {', '.join(va.CHAINS)}"}), 400
    if protocol not in va.CHAINS[chain]["protocols"]:
        return jsonify({"error": f"protocol must be one of: {', '.join(va.CHAINS[chain]['protocols'])} for chain {chain}"}), 400
    history = load_history(f"pos_{chain}:{protocol}:{token_id}")
    window_seconds = _RANGE_TO_SECONDS[range_key]
    if window_seconds is not None:
        cutoff = time.time() - window_seconds
        history = [s for s in history if s["ts"] >= cutoff]
    return jsonify({"snapshots": history, "range": range_key, "token_id": token_id, "protocol": protocol, "chain": chain})


@app.route("/api/closed")
def api_closed_positions():
    closed = _read_json_locked(_closed_positions_file_path(), [])
    closed_sorted = sorted(closed, key=lambda c: c["closed_at"], reverse=True)
    return jsonify({"closed": closed_sorted})


@app.route("/api/pool-volume/<int:token_id>")
def api_pool_volume(token_id):
    range_key = request.args.get("range", "30d")
    protocol = request.args.get("protocol", "uniswap")
    chain = request.args.get("chain", "base")
    if range_key not in _VOLUME_RANGE_DAYS:
        return jsonify({"error": "range must be one of: 7d, 30d, 60d, 90d, 180d"}), 400
    if chain not in va.CHAINS:
        return jsonify({"error": f"chain must be one of: {', '.join(va.CHAINS)}"}), 400
    if protocol not in va.CHAINS[chain]["protocols"]:
        return jsonify({"error": f"protocol must be one of: {', '.join(va.CHAINS[chain]['protocols'])} for chain {chain}"}), 400

    known = _read_json_locked(_known_positions_file_path(), {})
    entry = known.get(f"{chain}:{protocol}:{token_id}")
    pool_address = entry.get("pool_address") if entry else None
    if not pool_address:
        return jsonify({"error": "Pool address not yet known for this position — "
                                  "check back after the next snapshot cycle."}), 404
    try:
        gecko_network = va.CHAINS[chain]["gecko_network"]
        candles = get_pool_volume_usd(pool_address, _VOLUME_RANGE_DAYS[range_key], gecko_network)
    except Exception as e:
        app.logger.warning("Pool volume fetch failed for %s: %s", pool_address, e)
        return jsonify({"error": "Volume data unavailable right now"}), 502
    return jsonify({"candles": candles, "range": range_key, "token_id": token_id, "protocol": protocol, "chain": chain})


_snapshot_thread = threading.Thread(target=_snapshot_loop, daemon=True)
_snapshot_thread.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
