"""Sickle-level "LP vs Hold" for vfat.

vfat mints a NEW position NFT on every rebalance, so a per-position
comparison would skip exactly the rebalance costs we want to measure.
Instead treat each chain's Sickle as one portfolio:

  vs_hold = (tokens_now + sent_to_wallet - deposited_from_wallet) - tokens_at_start

every token valued at TODAY's price, so price moves cancel out and only
LP performance (fees + rewards - rebalance/IL costs) remains. Fee and
reward payouts to the wallet count as LP earnings; deposits are
subtracted so new money isn't mistaken for gains.

"Tokens" = every LP position the Sickle holds (directly, staked in
Pancake MasterChefV3, or in an Aerodrome gauge) valued as liquidity
amounts + uncollected fees + pending rewards, plus idle ERC20/ETH
sitting in the Sickle. Holdings at the start come from archive reads.
"""
import requests
from web3 import Web3

import vfat_adapter as va

WETH = {
    "base": "0x4200000000000000000000000000000000000006",
    "optimism": "0x4200000000000000000000000000000000000006",
    "mainnet": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}
ENUM_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "tokenOfOwnerByIndex", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "i", "type": "uint256"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "ownerOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "t", "type": "uint256"}], "outputs": [{"name": "", "type": "address"}]},
]
POSITIONS_ABI = [{
    "name": "positions", "type": "function", "stateMutability": "view",
    "inputs": [{"name": "tokenId", "type": "uint256"}],
    "outputs": [{"name": "nonce", "type": "uint96"}, {"name": "operator", "type": "address"},
                {"name": "token0", "type": "address"}, {"name": "token1", "type": "address"},
                {"name": "feeOrTickSpacing", "type": "int24"}, {"name": "tickLower", "type": "int24"},
                {"name": "tickUpper", "type": "int24"}, {"name": "liquidity", "type": "uint128"},
                {"name": "fg0", "type": "uint256"}, {"name": "fg1", "type": "uint256"},
                {"name": "owed0", "type": "uint128"}, {"name": "owed1", "type": "uint128"}]}]
COLLECT_ABI = [{
    "name": "collect", "type": "function", "stateMutability": "payable",
    "inputs": [{"name": "params", "type": "tuple", "components": [
        {"name": "tokenId", "type": "uint256"}, {"name": "recipient", "type": "address"},
        {"name": "amount0Max", "type": "uint128"}, {"name": "amount1Max", "type": "uint128"}]}],
    "outputs": [{"name": "amount0", "type": "uint256"}, {"name": "amount1", "type": "uint256"}]}]
GETPOOL_ABI = [{"name": "getPool", "type": "function", "stateMutability": "view",
                "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}, {"name": "f", "type": "int24"}],
                "outputs": [{"name": "", "type": "address"}]}]
GETPOOL_U24_ABI = [{"name": "getPool", "type": "function", "stateMutability": "view",
                    "inputs": [{"name": "a", "type": "address"}, {"name": "b", "type": "address"}, {"name": "f", "type": "uint24"}],
                    "outputs": [{"name": "", "type": "address"}]}]
BAL_ABI = [{"name": "balanceOf", "type": "function", "stateMutability": "view",
            "inputs": [{"name": "o", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]}]
MAX128 = 2 ** 128 - 1


def _add(d, addr, raw):
    if raw:
        k = Web3.to_checksum_address(addr)
        d[k] = d.get(k, 0) + int(raw)


def _slot0(w3, pool, block):
    raw = w3.eth.call({"to": pool, "data": "0x3850c7bd"}, block_identifier=block)  # slot0()
    sqrt_price = int.from_bytes(raw[0:32], "big")
    tick = int.from_bytes(raw[32:64], "big", signed=True)
    return sqrt_price, tick


def _position_tokens(w3, proto, cfg, tid, block, sickle, out, rewards):
    npm = w3.eth.contract(address=cfg["npm"], abi=POSITIONS_ABI + COLLECT_ABI + ENUM_ABI)
    (_n, _op, t0, t1, fee_or_ts, tl, tu, liq, _g0, _g1, _o0, _o1) = npm.functions.positions(tid).call(block_identifier=block)
    abi = GETPOOL_ABI if proto == "aerodrome" else GETPOOL_U24_ABI
    pool = w3.eth.contract(address=cfg["factory"], abi=abi).functions.getPool(t0, t1, fee_or_ts).call(block_identifier=block)
    sp, _tick = _slot0(w3, Web3.to_checksum_address(pool), block)
    a0, a1 = va._amounts_for_liquidity(sp / 2 ** 96, va._tick_to_sqrt_price(tl), va._tick_to_sqrt_price(tu), liq)
    _add(out, t0, int(a0))
    _add(out, t1, int(a1))
    owner = npm.functions.ownerOf(tid).call(block_identifier=block)
    try:
        f0, f1 = npm.functions.collect((tid, owner, MAX128, MAX128)).call({"from": owner}, block_identifier=block)
        _add(out, t0, f0)
        _add(out, t1, f1)
    except Exception:
        pass
    # Pending emissions (Pancake farm / Aerodrome gauge)
    try:
        if owner == va.PANCAKE_MASTERCHEF_V3:
            mc = w3.eth.contract(address=owner, abi=va.MASTERCHEF_V3_ABI)
            _add(rewards, va.CAKE_TOKEN_BASE, mc.functions.pendingCake(tid).call(block_identifier=block))
        elif proto == "aerodrome" and owner != sickle:
            g = w3.eth.contract(address=owner, abi=va.AERODROME_GAUGE_ABI)
            _add(rewards, g.functions.rewardToken().call(block_identifier=block),
                 g.functions.earned(sickle, tid).call(block_identifier=block))
    except Exception:
        pass
    return {t0, t1}


def holdings(w3, chain_key, sickle, block):
    """{token: raw} for everything the Sickle holds at `block` (positions
    + uncollected fees + pending rewards + idle balances), plus the list
    of position ids found."""
    chain_cfg = va.CHAINS[chain_key]
    out, rewards, tokens, found = {}, {}, set(), []
    for proto, cfg in chain_cfg["protocols"].items():
        c = w3.eth.contract(address=cfg["npm"], abi=ENUM_ABI)
        ids = set()
        try:
            n = c.functions.balanceOf(sickle).call(block_identifier=block)
            ids |= {c.functions.tokenOfOwnerByIndex(sickle, i).call(block_identifier=block) for i in range(n)}
        except Exception:
            pass
        if proto == "pancake":
            mc = w3.eth.contract(address=va.PANCAKE_MASTERCHEF_V3, abi=ENUM_ABI)
            try:
                n = mc.functions.balanceOf(sickle).call(block_identifier=block)
                ids |= {mc.functions.tokenOfOwnerByIndex(sickle, i).call(block_identifier=block) for i in range(n)}
            except Exception:
                pass
        if proto == "aerodrome":
            for tid in va.AERODROME_KNOWN_TOKEN_IDS:
                try:
                    c.functions.ownerOf(tid).call(block_identifier=block)
                    ids.add(tid)  # exists at this block (held by Sickle or its gauge)
                except Exception:
                    pass
        for tid in sorted(ids):
            tokens |= _position_tokens(w3, proto, cfg, tid, block, sickle, out, rewards)
            found.append(f"{proto}#{tid}")
    for k, v in rewards.items():
        _add(out, k, v)
        tokens.add(k)
    return out, tokens, found


def idle_balances(w3, chain_key, sickle, block, tokens):
    out = {}
    for t in tokens:
        try:
            _add(out, t, w3.eth.contract(address=Web3.to_checksum_address(t), abi=BAL_ABI)
                 .functions.balanceOf(sickle).call(block_identifier=block))
        except Exception:
            pass
    _add(out, WETH[chain_key], w3.eth.get_balance(sickle, block_identifier=block))  # native ETH ~ WETH
    return out


REAL_TOKENS = {"WETH", "ETH", "USDC", "USDC.E", "USDBC", "USDT", "DAI", "CBBTC", "WBTC", "AERO", "CAKE", "OP"}


def _transfers(rpc_url, **kw):
    """alchemy_getAssetTransfers incl. native ETH sent by contracts
    ('internal' — how a Sickle pays out ETH); falls back to
    external+erc20 on chains that don't support 'internal'."""
    out, page = [], None
    cats = ["external", "erc20", "internal"]
    while True:
        params = {"toBlock": "latest", "category": cats, "maxCount": "0x3e8", **kw}
        if page:
            params["pageKey"] = page
        r = requests.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers",
                                         "params": [params]}, timeout=30).json()
        if "error" in r and "internal" in cats:
            cats, page, out = ["external", "erc20"], None, []
            continue
        if "error" in r:
            raise RuntimeError(r["error"])
        out += r["result"]["transfers"]
        page = r["result"].get("pageKey")
        if not page:
            return out


def wallet_flows(rpc_url, chain_key, wallet, sickle, from_block):
    """(deposits, withdrawals) as {token: raw}. Uses every wallet transfer
    inside a transaction that touches the Sickle, so money routed via a
    vfat router or paid out as native ETH is caught, not just direct
    wallet<->Sickle ERC20 transfers."""
    fb = hex(from_block)
    sickle_txs = {t["hash"] for t in _transfers(rpc_url, fromBlock=fb, fromAddress=sickle)}
    sickle_txs |= {t["hash"] for t in _transfers(rpc_url, fromBlock=fb, toAddress=sickle)}
    deposits, withdrawals = {}, {}
    for direction, kw, bucket in (("in", {"fromAddress": wallet}, deposits), ("out", {"toAddress": wallet}, withdrawals)):
        for t in _transfers(rpc_url, fromBlock=fb, **kw):
            if t["hash"] not in sickle_txs:
                continue
            addr = (t.get("rawContract") or {}).get("address") or WETH[chain_key]
            raw = int((t.get("rawContract") or {}).get("value") or "0x0", 16)
            _add(bucket, addr, raw)
    return deposits, withdrawals


def block_at(w3, ts):
    lo, hi = 1, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if w3.eth.get_block(mid)["timestamp"] < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def compute_chain(w3, rpc_url, chain_key, sickle, wallet, start_block):
    """Raw token dicts for one chain; valuation happens in the caller."""
    start, tokens_s, found_s = holdings(w3, chain_key, sickle, start_block)
    now, tokens_n, found_n = holdings(w3, chain_key, sickle, "latest")
    inflow, outflow = wallet_flows(rpc_url, chain_key, wallet, sickle, start_block)
    position_tokens = {Web3.to_checksum_address(t) for t in tokens_s | tokens_n}
    tokens = position_tokens | set(inflow) | set(outflow)
    for k, v in idle_balances(w3, chain_key, sickle, start_block, tokens).items():
        _add(start, k, v)
    for k, v in idle_balances(w3, chain_key, sickle, "latest", tokens).items():
        _add(now, k, v)
    return {"start": start, "now": now, "in": inflow, "out": outflow, "position_tokens": position_tokens,
            "positions_start": found_s, "positions_now": found_n, "start_block": start_block}


def allowed_tokens(tokens, position_tokens, symbols):
    """Position tokens + known majors only — spam airdrops (dozens hit the
    Sickle) must never be priced into the result."""
    return {t for t in tokens if t in position_tokens or symbols.get(t, "").upper() in REAL_TOKENS}


def value(raw_by_token, prices, decimals, allowed=None):
    """USD value of a {token: raw} dict; returns (usd, missing_price_tokens)."""
    total, missing = 0.0, []
    for t, raw in raw_by_token.items():
        if allowed is not None and t not in allowed:
            continue
        p = prices.get(t.lower())
        if p is None:
            missing.append(t)
            continue
        total += raw / 10 ** decimals[t] * p
    return total, missing
