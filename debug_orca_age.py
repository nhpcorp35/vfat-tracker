"""Check the Position account's transaction history to sanity-check
whether $73 in accumulated fees on a $20 position is even plausible
given how long it's actually been open."""
import os
import requests
from solders.pubkey import Pubkey

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
WHIRLPOOL_PROGRAM = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
POSITION_MINT = "6eeinqbDCX1sHJPuuAqs6Rzs71v2CGCbESJGvXP68UnL"


def rpc_call(method, params):
    resp = requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"{method} failed: {data['error']}")
    return data["result"]


def main():
    mint = Pubkey.from_string(POSITION_MINT)
    position_pda, _ = Pubkey.find_program_address([b"position", bytes(mint)], WHIRLPOOL_PROGRAM)
    print(f"Position PDA: {position_pda}")

    sigs = rpc_call("getSignaturesForAddress", [str(position_pda), {"limit": 20}])
    print(f"Found {len(sigs)} recent signatures (most recent first):")
    for s in sigs:
        import datetime
        block_time = s.get("blockTime")
        dt = datetime.datetime.utcfromtimestamp(block_time).isoformat() if block_time else "unknown"
        print(f"  {s['signature'][:20]}... at {dt}, slot {s['slot']}, err={s.get('err')}")

    if sigs:
        oldest = sigs[-1]
        newest = sigs[0]
        print(f"\nNewest tx: {newest.get('blockTime')}")
        print(f"Oldest tx in this page (may not be position creation if >20 txs exist): {oldest.get('blockTime')}")


if __name__ == "__main__":
    main()
# trigger 1789417708
