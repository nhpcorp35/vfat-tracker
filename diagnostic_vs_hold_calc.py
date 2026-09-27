"""Runs vs_hold.compute_chain for every chain and prints the full breakdown."""
import os, time, requests
from web3 import Web3
from web3.middleware import geth_poa_middleware
import vfat_adapter as va
import vs_hold as vh

START_TS = int(os.environ.get("VS_START_TS", "1789171200"))  # 2026-09-12 00:00 UTC
WALLET = Web3.to_checksum_address(os.environ.get("DEFAULT_WALLET") or "0xc33Fc161686ED2B8649162Ff9BfC3ED3a7f24801")
BASE = os.environ["ALCHEMY_BASE"]
URLS = {"base": BASE, "optimism": BASE.replace("base-mainnet", "opt-mainnet"), "mainnet": BASE.replace("base-mainnet", "eth-mainnet")}
GECKO = {"base": "base", "optimism": "optimism", "mainnet": "eth"}

def prices(net, addrs):
    r = requests.get(f"https://api.geckoterminal.com/api/v2/simple/networks/{net}/token_price/{','.join(addrs)}", timeout=20).json()
    return {k.lower(): float(v) for k, v in r.get("data", {}).get("attributes", {}).get("token_prices", {}).items() if v}

grand = 0.0
for chain in ("base", "optimism", "mainnet"):
    print(f"\n===== {chain} =====", flush=True)
    try:
        w3 = Web3(Web3.HTTPProvider(URLS[chain]))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        cfg = va.CHAINS[chain]
        sickle = va.resolve_sickle(w3, WALLET) if cfg["sickle_resolution"] == "dynamic" else cfg["fixed_sickle_address"]
        blk = vh.block_at(w3, START_TS)
        r = vh.compute_chain(w3, URLS[chain], chain, sickle, WALLET, blk)
        toks = set(r["start"]) | set(r["now"]) | set(r["in"]) | set(r["out"])
        meta = {t: va._token_meta(w3, t) for t in toks}
        dec = {t: meta[t][1] for t in toks}
        allowed = vh.allowed_tokens(toks, r["position_tokens"], {t: meta[t][0] for t in toks})
        px = prices(GECKO[chain], list(allowed)) if allowed else {}
        print(f"positions at start: {r['positions_start']}  now: {r['positions_now']}", flush=True)
        for t in sorted(allowed, key=lambda t: meta[t][0]):
            f = lambda d: d.get(t, 0) / 10 ** dec[t]
            print(f"  {meta[t][0]:>6} price={px.get(t.lower())}  start={f(r['start']):.6f} now={f(r['now']):.6f} in={f(r['in']):.6f} out={f(r['out']):.6f}", flush=True)
        vs, ms = vh.value(r["start"], px, dec, allowed)
        vn, mn = vh.value(r["now"], px, dec, allowed)
        vi, mi = vh.value(r["in"], px, dec, allowed)
        vo, mo = vh.value(r["out"], px, dec, allowed)
        res = (vn + vo - vi) - vs
        grand += res
        print(f"  USD @ today's prices: start={vs:.2f} now={vn:.2f} in={vi:.2f} out={vo:.2f}  => vs hold {res:+.2f}", flush=True)
        missing = set(ms + mn + mi + mo)
        if missing:
            print(f"  missing prices: {[meta[t][0] for t in missing]}", flush=True)
    except Exception as e:
        print(f"  chain failed: {e}", flush=True)
    time.sleep(1)
print(f"\nTOTAL vs hold (all chains): {grand:+.2f}\nDONE", flush=True)
