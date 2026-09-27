"""Every transfer touching the Base Sickle (any counterparty) and every
transfer INTO the wallet in the same transactions, since Sep 12."""
import os, requests
from web3 import Web3
URL = os.environ["ALCHEMY_BASE"]
W = "0xc33Fc161686ED2B8649162Ff9BfC3ED3a7f24801"
S = "0x7664C1834794255Fd83a6B8f091cdCaCfB4D390c"
START = 51190927

def q(**kw):
    out, page = [], None
    while True:
        p = {"fromBlock": hex(START), "toBlock": "latest", "category": ["external", "erc20", "internal"], "withMetadata": True, "maxCount": "0x3e8", **kw}
        if page: p["pageKey"] = page
        r = requests.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [p]}, timeout=30).json()
        if "error" in r:
            p["category"] = ["external", "erc20"]
            r = requests.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [p]}, timeout=30).json()
            if "error" in r: raise RuntimeError(r["error"])
        out += r["result"]["transfers"]; page = r["result"].get("pageKey")
        if not page: return out

sickle_out = q(fromAddress=S)
sickle_in = q(toAddress=S)
txs = {t["hash"] for t in sickle_out + sickle_in}
wallet_in = [t for t in q(toAddress=W) if t["hash"] in txs]
wallet_out = [t for t in q(fromAddress=W) if t["hash"] in txs]
def show(label, ts, key):
    agg = {}
    for t in ts:
        k = (t[key], t["asset"], t["category"])
        agg[k] = agg.get(k, 0) + (t["value"] or 0)
    print(f"\n{label}: {len(ts)} transfers", flush=True)
    for (cp, asset, cat), v in sorted(agg.items(), key=lambda x: -abs(x[1] or 0)):
        print(f"  {cat:8} {asset:6} {v:>16.6f}  counterparty={cp}", flush=True)
show("FROM Sickle (by recipient)", sickle_out, "to")
show("TO Sickle (by sender)", sickle_in, "from")
show("TO wallet in Sickle txs (by sender)", wallet_in, "from")
show("FROM wallet in Sickle txs (by recipient)", wallet_out, "to")
print("DONE", flush=True)
