"""Rescan the wallet for position-shaped tokens, excluding the already-
known Orca position and the two Jupiter vaults, to find the new test
position's mint automatically."""
import os
import requests

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
WALLET = "FF9V5DXtZGC5nVwBKg5WBRzqo1NirJxqyaS7VTAAa2z4"
KNOWN_MINTS = {
    "4UTiNMQfPZqjeGDww3SkrpzWndJUhnBFRCch1o9rmcz6",  # jupiter vault 7
    "6zYrZ6Z8e16Gv2aGu8HDZpWF1qkjdC7xJ1dEgz5jhPju",  # jupiter vault 8
    "6eeinqbDCX1sHJPuuAqs6Rzs71v2CGCbESJGvXP68UnL",  # original Orca position
}

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
    for program_id, label in [(SPL_TOKEN_PROGRAM, "SPL Token"), (TOKEN_2022_PROGRAM, "Token-2022")]:
        result = rpc_call("getTokenAccountsByOwner", [
            WALLET, {"programId": program_id}, {"encoding": "jsonParsed"},
        ])
        accounts = result.get("value", [])
        for acc in accounts:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = info["tokenAmount"]["uiAmount"]
            decimals = info["tokenAmount"]["decimals"]
            mint = info["mint"]
            if amount == 1 and decimals == 0:
                is_new = mint not in KNOWN_MINTS
                print(f"[{label}] mint={mint} {'<<< NEW' if is_new else '(already known)'}")


if __name__ == "__main__":
    main()
