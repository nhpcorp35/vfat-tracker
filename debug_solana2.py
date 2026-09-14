"""
Identify which CLMM protocol each candidate position NFT belongs to,
using the universal Metaplex token-metadata PDA (same derivation for
any Solana NFT regardless of which program minted it) rather than
guessing each protocol's own position-PDA seed scheme.
"""
import os
import base64
import struct
import requests
from solders.pubkey import Pubkey

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")

CANDIDATE_MINTS = [
    "4UTiNMQfPZqjeGDww3SkrpzWndJUhnBFRCch1o9rmcz6",
    "6zYrZ6Z8e16Gv2aGu8HDZpWF1qkjdC7xJ1dEgz5jhPju",
    "6eeinqbDCX1sHJPuuAqs6Rzs71v2CGCbESJGvXP68UnL",
]

# For labeling once we see the name/symbol/update_authority — don't
# hardcode assumptions, just print raw findings.
KNOWN_PROGRAMS = {
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpool",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
}


def rpc_call(method, params):
    resp = requests.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"{method} failed: {data['error']}")
    return data["result"]


def parse_metadata(raw_bytes):
    """Metaplex Metadata account: key(1) + update_authority(32) + mint(32)
    + name(4-byte len + bytes) + symbol(4-byte len + bytes) + uri(...)"""
    offset = 1 + 32  # skip key + update_authority
    update_authority = base64.b16encode(raw_bytes[1:33]).decode()  # keep as hex for now, convert below
    mint_bytes = raw_bytes[33:65]
    offset = 65
    name_len = struct.unpack_from("<I", raw_bytes, offset)[0]
    offset += 4
    name = raw_bytes[offset:offset + name_len].decode("utf-8", errors="replace").rstrip("\x00")
    offset += name_len
    symbol_len = struct.unpack_from("<I", raw_bytes, offset)[0]
    offset += 4
    symbol = raw_bytes[offset:offset + symbol_len].decode("utf-8", errors="replace").rstrip("\x00")
    return name.strip(), symbol.strip()


def main():
    for mint_str in CANDIDATE_MINTS:
        print(f"\n--- Mint: {mint_str} ---")
        mint = Pubkey.from_string(mint_str)
        metadata_pda, bump = Pubkey.find_program_address(
            [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint)],
            METADATA_PROGRAM_ID,
        )
        print(f"Metadata PDA: {metadata_pda}")

        result = rpc_call("getAccountInfo", [str(metadata_pda), {"encoding": "base64"}])
        if result["value"] is None:
            print("No metadata account found at that PDA.")
            continue

        data_b64 = result["value"]["data"][0]
        owner_program = result["value"]["owner"]
        raw = base64.b64decode(data_b64)
        print(f"Metadata account owner (should be Token Metadata program): {owner_program}")

        try:
            name, symbol = parse_metadata(raw)
            print(f"NFT name: {name!r}")
            print(f"NFT symbol: {symbol!r}")
        except Exception as e:
            print(f"Failed to parse metadata: {e}")

        # Also check the update_authority against known program IDs directly
        update_authority_bytes = raw[1:33]
        update_authority_pubkey = str(Pubkey(update_authority_bytes))
        label = KNOWN_PROGRAMS.get(update_authority_pubkey, "unknown")
        print(f"Update authority: {update_authority_pubkey} ({label})")


if __name__ == "__main__":
    main()
