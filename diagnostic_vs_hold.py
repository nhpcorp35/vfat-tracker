"""vfat vs-hold feasibility check (read-only).
For each chain: what LP positions the Sickle held at START_TS (direct in
the NPM, staked in Pancake MasterChefV3, or in an Aerodrome gauge), and
every token transfer between the user's wallet and the Sickle since then
(alchemy_getAssetTransfers)."""
import os, json, time, requests
from web3 import Web3
import vfat_adapter as va

START_TS = int(os.environ.get("VS_START_TS", "1789171200"))  # 2026-09-12 00:00 UTC
WALLET = Web3.to_checksum_address(os.environ.get("DEFAULT_WALLET") or "0xc33Fc161686ED2B8649162Ff9BfC3ED3a7f24801")
ALCHEMY_BASE = os.environ["ALCHEMY_BASE"]

ENUM_ABI = [
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "tokenOfOwnerByIndex", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "i", "type": "uint256"}], "outputs": [{"name": "", "type": "uint256"}]},
    {"name": "ownerOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "t", "type": "uint256"}], "outputs": [{"name": "", "type": "address"}]},
]


def block_at(w3, ts):
    lo, hi = 1, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if w3.eth.get_block(mid)["timestamp"] < ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


def enum_owned(w3, contract_addr, owner, block):
    c = w3.eth.contract(address=contract_addr, abi=ENUM_ABI)
    n = c.functions.balanceOf(owner).call(block_identifier=block)
    return [c.functions.tokenOfOwnerByIndex(owner, i).call(block_identifier=block) for i in range(n)]


def transfers(rpc_url, frm, to, from_block):
    out, page = [], None
    while True:
        params = {"fromBlock": hex(from_block), "toBlock": "latest", "fromAddress": frm, "toAddress": to,
                  "category": ["external", "erc20"], "withMetadata": True, "maxCount": "0x3e8"}
        if page:
            params["pageKey"] = page
        r = requests.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": "alchemy_getAssetTransfers", "params": [params]}, timeout=30).json()
        if "error" in r:
            raise RuntimeError(r["error"])
        res = r["result"]
        out += res["transfers"]
        page = res.get("pageKey")
        if not page:
            return out


for chain_key, chain_cfg in va.CHAINS.items():
    print(f"\n===== {chain_key} =====", flush=True)
    try:
        w3 = va_w3 = None
        if chain_key == "base":
            url = ALCHEMY_BASE
        elif chain_key == "mainnet":
            url = ALCHEMY_BASE.replace("base-mainnet", "eth-mainnet")
        else:
            url = ALCHEMY_BASE.replace("base-mainnet", "opt-mainnet")
        w3 = Web3(Web3.HTTPProvider(url))
        sickle = va.resolve_sickle(w3, WALLET) if chain_cfg["sickle_resolution"] == "dynamic" else chain_cfg["fixed_sickle_address"]
        blk = block_at(w3, START_TS)
        print(f"sickle={sickle} start_block={blk} head={w3.eth.block_number}", flush=True)
        for pk, cfg in chain_cfg["protocols"].items():
            try:
                direct = enum_owned(w3, cfg["npm"], sickle, blk)
            except Exception as e:
                direct = f"enum failed: {e}"
            print(f"  {pk}: held directly by Sickle at start: {direct}", flush=True)
            try:
                now_direct = enum_owned(w3, cfg["npm"], sickle, "latest")
            except Exception as e:
                now_direct = f"enum failed: {e}"
            print(f"  {pk}: held directly by Sickle now: {now_direct}", flush=True)
        if chain_key == "base":
            try:
                print(f"  pancake MasterChefV3 staked at start: {enum_owned(w3, va.PANCAKE_MASTERCHEF_V3, sickle, blk)}", flush=True)
                print(f"  pancake MasterChefV3 staked now: {enum_owned(w3, va.PANCAKE_MASTERCHEF_V3, sickle, 'latest')}", flush=True)
            except Exception as e:
                print(f"  MasterChef enum failed: {e}", flush=True)
            npm = w3.eth.contract(address=va.AERODROME_NPM, abi=ENUM_ABI)
            for tid in va.AERODROME_KNOWN_TOKEN_IDS:
                for tag, b in (("start", blk), ("now", "latest")):
                    try:
                        print(f"  aerodrome #{tid} owner at {tag}: {npm.functions.ownerOf(tid).call(block_identifier=b)}", flush=True)
                    except Exception as e:
                        print(f"  aerodrome #{tid} at {tag}: not minted/burned ({str(e)[:60]})", flush=True)
        for label, frm, to in (("wallet->sickle", WALLET, sickle), ("sickle->wallet", sickle, WALLET)):
            try:
                ts = transfers(url, frm, to, blk)
                print(f"  {label}: {len(ts)} transfers", flush=True)
                for t in ts[:15]:
                    print(f"    {t['metadata']['blockTimestamp']} {t['asset']} {t['value']} blk={int(t['blockNum'], 16)}", flush=True)
            except Exception as e:
                print(f"  {label}: transfer query failed: {e}", flush=True)
    except Exception as e:
        print(f"  chain failed: {e}", flush=True)
    time.sleep(1)
print("\nDONE", flush=True)
