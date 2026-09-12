"""
vfat-tracker — standalone service.
Tracks vfat/Sickle-held Uniswap V3 positions on Base for a wallet.

Uniswap V3 only for now (per agreed build order) — PancakeSwap V3 and
Aerodrome Slipstream (gauge-staked, confirmed via a real harvestFor tx)
are separate adapters, not yet built.
"""

import os
import time
import base64
import logging

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

_w3 = None


def get_w3():
    global _w3
    if _w3 is None and ALCHEMY_BASE:
        _w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    return _w3


# ── Cache ────────────────────────────────────────────────────────────────
_cache = {}
_stale_cache = {}
CACHE_TTL = 120

# ── Token price lookup (GeckoTerminal free/keyless API) ────────────────────
_GECKOTERMINAL_TOKEN_PRICE_URL = "https://api.geckoterminal.com/api/v2/simple/networks/base/token_price/{}"


def get_token_prices_usd(addresses: list) -> dict:
    if not addresses:
        return {}
    unique = sorted(set(a.lower() for a in addresses))
    url = _GECKOTERMINAL_TOKEN_PRICE_URL.format(",".join(unique))
    try:
        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        token_prices = data.get("data", {}).get("attributes", {}).get("token_prices", {})
        return {addr.lower(): float(price) for addr, price in token_prices.items()}
    except Exception as e:
        app.logger.warning("GeckoTerminal price fetch failed: %s", e)
        return {}


def enrich_with_usd(positions: list) -> list:
    """Adds USD values and range-bar-support fields. Fields are None
    where price data wasn't available — never fabricated."""
    all_addresses = []
    for p in positions:
        all_addresses.append(p["token0"]["address"])
        all_addresses.append(p["token1"]["address"])
    prices = get_token_prices_usd(all_addresses)

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
    return {
        "total_value_usd": total_value_usd if total_value_usd > 0 else None,
        "total_fees_usd": total_fees_usd if total_fees_usd > 0 else None,
        "position_count": len(positions),
        "out_of_range_count": sum(1 for p in positions if not p["in_range"]),
    }


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

    w3 = get_w3()
    if not w3:
        return jsonify({"error": "ALCHEMY_BASE RPC not configured"}), 500

    try:
        sickle_address = va.resolve_sickle(w3, wallet)
        if sickle_address is None:
            result = {"sickle_address": None, "positions": [], "portfolio": compute_portfolio_summary([]),
                       "fetched_at": time.time(), "note": "No Sickle deployed for this wallet on Base."}
            _cache[cache_key] = result
            return jsonify({**result, "cached": False})

        token_ids = va.discover_current_token_ids(w3, sickle_address)
        positions = [va.fetch_position(w3, tid) for tid in token_ids]
        positions = enrich_with_usd(positions)
    except Exception as e:
        app.logger.error("Position fetch failed for %s: %s", wallet, e)
        stale = _stale_cache.get(cache_key)
        if stale:
            app.logger.warning("Serving stale data for %s", wallet)
            return jsonify({**stale, "cached": True, "stale": True})
        return jsonify({"error": str(e)}), 500

    portfolio = compute_portfolio_summary(positions)
    result = {
        "sickle_address": sickle_address,
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
