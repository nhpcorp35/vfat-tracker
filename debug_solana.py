"""
Solana reconnaissance — no solana-py dependency, just raw JSON-RPC over
HTTP (works with any endpoint, no extra install). Goal: find which
concentrated-liquidity protocol(s) this wallet actually has positions
in, rather than assume from "concentrated" alone — Orca Whirlpools,
Raydium CLMM, and Meteora DLMM are different programs entirely, not
variations on one shape like the EVM Uniswap forks were.

Step 1: basic connectivity + list of SPL token accounts owned by the
wallet with amount=1, decimals=0 — the standard signature of a
position NFT on Solana, across all three of the major CLMM protocols.
"""
import os
import requests

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
WALLET = "FF9V5DXtZGC5nVwBKg5WBRzqo1NirJxqyaS7VTAAa2z4"

SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def rpc_call(method, params):
    resp = requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"{method} failed: {data['error']}")
    return data["result"]


def main():
    print(f"RPC: {RPC_URL}")
    health = None
    try:
        health = rpc_call("getHealth", [])
        print(f"getHealth: {health}")
    except Exception as e:
        print(f"getHealth failed (may not be supported, non-fatal): {e}")

    version = rpc_call("getVersion", [])
    print(f"getVersion: {version}")

    slot = rpc_call("getSlot", [])
    print(f"Current slot: {slot}")

    candidate_mints = []
    for program_id, label in [(SPL_TOKEN_PROGRAM, "SPL Token"), (TOKEN_2022_PROGRAM, "Token-2022")]:
        print(f"\n--- Token accounts owned by wallet, program={label} ---")
        result = rpc_call("getTokenAccountsByOwner", [
            WALLET,
            {"programId": program_id},
            {"encoding": "jsonParsed"},
        ])
        accounts = result.get("value", [])
        print(f"Total token accounts under this program: {len(accounts)}")
        for acc in accounts:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = info["tokenAmount"]["uiAmount"]
            decimals = info["tokenAmount"]["decimals"]
            mint = info["mint"]
            if amount == 1 and decimals == 0:
                print(f"  CANDIDATE NFT: mint={mint}")
                candidate_mints.append(mint)

    print(f"\nTotal candidate position NFTs found: {len(candidate_mints)}")
    for m in candidate_mints:
        print(f"  {m}")


if __name__ == "__main__":
    main()
