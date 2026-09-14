"""
Fetch and decode the real Position + Whirlpool accounts for the
confirmed Orca position (6eeinqbDCX1sHJPuuAqs6Rzs71v2CGCbESJGvXP68UnL),
verifying against known-real values from v3.lptracker.info (SOL/USDC,
~$19.57 live value, in range) before building the production adapter.

Struct layouts confirmed directly from orca-so/whirlpools' own GitHub
source (state/position.rs, state/whirlpool.rs), not guessed.
"""
import os
import base64
import struct
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


def get_account_bytes(pubkey_str):
    result = rpc_call("getAccountInfo", [pubkey_str, {"encoding": "base64"}])
    if result["value"] is None:
        return None
    return base64.b64decode(result["value"]["data"][0])


def pk_at(raw, offset):
    return str(Pubkey(raw[offset:offset + 32]))


def u16_at(raw, offset):
    return struct.unpack_from("<H", raw, offset)[0]


def u128_at(raw, offset):
    return int.from_bytes(raw[offset:offset + 16], "little", signed=False)


def i32_at(raw, offset):
    return struct.unpack_from("<i", raw, offset)[0]


def u64_at(raw, offset):
    return struct.unpack_from("<Q", raw, offset)[0]


def main():
    mint = Pubkey.from_string(POSITION_MINT)
    position_pda, bump = Pubkey.find_program_address(
        [b"position", bytes(mint)], WHIRLPOOL_PROGRAM
    )
    print(f"Position PDA: {position_pda}")

    raw = get_account_bytes(str(position_pda))
    if raw is None:
        print("FAILED: no Position account found at that PDA.")
        return
    print(f"Position account size: {len(raw)} bytes")

    # Position struct (after 8-byte Anchor discriminator):
    whirlpool_addr = pk_at(raw, 8)
    position_mint = pk_at(raw, 40)
    liquidity = u128_at(raw, 72)
    tick_lower = i32_at(raw, 88)
    tick_upper = i32_at(raw, 92)
    fee_growth_checkpoint_a = u128_at(raw, 96)
    fee_owed_a = u64_at(raw, 112)
    fee_growth_checkpoint_b = u128_at(raw, 120)
    fee_owed_b = u64_at(raw, 128)

    print(f"\nwhirlpool: {whirlpool_addr}")
    print(f"position_mint: {position_mint} (matches input: {position_mint == POSITION_MINT})")
    print(f"liquidity: {liquidity}")
    print(f"tick_lower: {tick_lower}, tick_upper: {tick_upper}")
    print(f"fee_owed_a (raw): {fee_owed_a}")
    print(f"fee_owed_b (raw): {fee_owed_b}")

    print(f"\n--- Whirlpool account ({whirlpool_addr}) ---")
    wp_raw = get_account_bytes(whirlpool_addr)
    if wp_raw is None:
        print("FAILED: no Whirlpool account found.")
        return
    print(f"Whirlpool account size: {len(wp_raw)} bytes")

    tick_spacing = u16_at(wp_raw, 8 + 32 + 1)
    fee_rate = u16_at(wp_raw, 8 + 32 + 1 + 2 + 2)
    pool_liquidity = u128_at(wp_raw, 49)
    sqrt_price = u128_at(wp_raw, 65)
    tick_current_index = i32_at(wp_raw, 81)
    token_mint_a = pk_at(wp_raw, 101)
    token_mint_b = pk_at(wp_raw, 181)

    print(f"tick_spacing: {tick_spacing}")
    print(f"fee_rate (hundredths of a bip): {fee_rate}")
    print(f"pool liquidity: {pool_liquidity}")
    print(f"sqrt_price (Q64.64): {sqrt_price}")
    print(f"tick_current_index: {tick_current_index}")
    print(f"token_mint_a: {token_mint_a}")
    print(f"token_mint_b: {token_mint_b}")

    in_range = tick_lower <= tick_current_index < tick_upper
    print(f"\nin_range (our calc): {in_range} (expect True, per screenshot 'In range')")

    # Human price from sqrt_price (Q64.64): price = (sqrt_price / 2^64)^2, decimal-adjusted
    sqrt_price_float = sqrt_price / (2 ** 64)
    raw_price = sqrt_price_float ** 2
    print(f"\nraw price (token_b per token_a, NOT decimal-adjusted yet): {raw_price}")
    print("(need token decimals to decimal-adjust and confirm against the ~$19-20 SOL/USDC position)")


if __name__ == "__main__":
    main()
