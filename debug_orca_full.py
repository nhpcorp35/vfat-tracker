"""
Full end-to-end verification: real Position + Whirlpool + both
TickArrays for our confirmed position, computing live fee-growth-based
uncollected fees and token amounts — same math as the EVM adapters
tonight, just Q64.64 fixed point instead of Q128, and tick data read
from fixed-size TickArray accounts instead of one-account-per-tick.
Comparing against the known real value ($19.57) from the screenshot.
"""
import os
import base64
import struct
import requests
from solders.pubkey import Pubkey

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
WHIRLPOOL_PROGRAM = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
POSITION_MINT = "CsezH1MBuFYece5kyFm2bTAoJMYEfdEs1yGJwsbzNGnG"  # NEW fresh test position
TICK_ARRAY_SIZE = 88
Q64 = 2 ** 64


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


def get_multiple_accounts(pubkey_strs):
    result = rpc_call("getMultipleAccounts", [pubkey_strs, {"encoding": "base64"}])
    out = []
    for v in result["value"]:
        out.append(base64.b64decode(v["data"][0]) if v else None)
    return out


def pk_at(raw, o): return str(Pubkey(raw[o:o + 32]))
def u16_at(raw, o): return struct.unpack_from("<H", raw, o)[0]
def u128_at(raw, o): return int.from_bytes(raw[o:o + 16], "little", signed=False)
def i128_at(raw, o): return int.from_bytes(raw[o:o + 16], "little", signed=True)
def i32_at(raw, o): return struct.unpack_from("<i", raw, o)[0]
def u64_at(raw, o): return struct.unpack_from("<Q", raw, o)[0]
def u8_at(raw, o): return raw[o]


def tick_array_start_index(tick_index, tick_spacing):
    ticks_in_array = TICK_ARRAY_SIZE * tick_spacing
    return (tick_index // ticks_in_array) * ticks_in_array


def derive_tick_array_pda(whirlpool, start_tick_index):
    seeds = [b"tick_array", bytes(whirlpool), str(start_tick_index).encode()]
    pda, _ = Pubkey.find_program_address(seeds, WHIRLPOOL_PROGRAM)
    return pda


def get_tick_fee_growth_outside(tick_array_raw, tick_index, start_tick_index, tick_spacing):
    """Tick struct: initialized(1) + liquidity_net i128(16) + liquidity_gross u128(16)
    + fee_growth_outside_a u128(16) + fee_growth_outside_b u128(16) + reward_growths_outside[3] u128(48)
    = 113 bytes each. TickArray header: discriminator(8) + start_tick_index(4) + whirlpool(32) = 44 bytes.
    Returns (initialized, fee_growth_outside_a, fee_growth_outside_b) — initialized MUST be
    checked before trusting the outside values (see fee_growth_inside)."""
    offset_in_array = (tick_index - start_tick_index) // tick_spacing
    tick_offset = 44 + offset_in_array * 113
    initialized = tick_array_raw[tick_offset] != 0
    fg_a = u128_at(tick_array_raw, tick_offset + 1 + 16 + 16)
    fg_b = u128_at(tick_array_raw, tick_offset + 1 + 16 + 16 + 16)
    return initialized, fg_a, fg_b


def fee_growth_inside(current_tick, tick_lower, tick_upper, fg_global_a, fg_global_b,
                       lower_initialized, lower_out_a, lower_out_b,
                       upper_initialized, upper_out_a, upper_out_b):
    """Exact match to Orca's real next_fee_growths_inside (verified against
    their actual GitHub source, not assumed from the Uniswap textbook
    formula) — the initialized check is the part that was missing before,
    and it's what was causing the huge false fee numbers: an uninitialized
    tick's stored fee_growth_outside is stale/meaningless and must NOT be
    used, per Orca's own 'by convention' comment in the real function."""
    if not lower_initialized:
        below_a, below_b = fg_global_a, fg_global_b
    elif current_tick < tick_lower:
        below_a = (fg_global_a - lower_out_a) % (2 ** 128)
        below_b = (fg_global_b - lower_out_b) % (2 ** 128)
    else:
        below_a, below_b = lower_out_a, lower_out_b

    if not upper_initialized:
        above_a, above_b = 0, 0
    elif current_tick < tick_upper:
        above_a, above_b = upper_out_a, upper_out_b
    else:
        above_a = (fg_global_a - upper_out_a) % (2 ** 128)
        above_b = (fg_global_b - upper_out_b) % (2 ** 128)

    inside_a = (fg_global_a - below_a - above_a) % (2 ** 128)
    inside_b = (fg_global_b - below_b - above_b) % (2 ** 128)
    return inside_a, inside_b


def tick_to_sqrt_price(tick):
    return 1.0001 ** (tick / 2)


def amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, liquidity):
    if sqrt_price <= sqrt_lower:
        amount_a = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount_b = 0
    elif sqrt_price < sqrt_upper:
        amount_a = liquidity * (1 / sqrt_price - 1 / sqrt_upper)
        amount_b = liquidity * (sqrt_price - sqrt_lower)
    else:
        amount_a = 0
        amount_b = liquidity * (sqrt_upper - sqrt_lower)
    return amount_a, amount_b


def main():
    mint = Pubkey.from_string(POSITION_MINT)
    position_pda, _ = Pubkey.find_program_address([b"position", bytes(mint)], WHIRLPOOL_PROGRAM)
    pos_raw = get_account_bytes(str(position_pda))

    whirlpool_addr = pk_at(pos_raw, 8)
    liquidity = u128_at(pos_raw, 72)
    tick_lower = i32_at(pos_raw, 88)
    tick_upper = i32_at(pos_raw, 92)
    fee_growth_checkpoint_a = u128_at(pos_raw, 96)
    fee_owed_a = u64_at(pos_raw, 112)
    fee_growth_checkpoint_b = u128_at(pos_raw, 120)
    fee_owed_b = u64_at(pos_raw, 136)

    wp_raw = get_account_bytes(whirlpool_addr)
    tick_spacing = u16_at(wp_raw, 41)
    sqrt_price_raw = u128_at(wp_raw, 65)
    tick_current = i32_at(wp_raw, 81)
    token_mint_a = pk_at(wp_raw, 101)
    token_mint_b = pk_at(wp_raw, 181)
    fg_global_a = u128_at(wp_raw, 165)
    fg_global_b = u128_at(wp_raw, 245)

    start_lower = tick_array_start_index(tick_lower, tick_spacing)
    start_upper = tick_array_start_index(tick_upper, tick_spacing)
    pda_lower = derive_tick_array_pda(Pubkey.from_string(whirlpool_addr), start_lower)
    pda_upper = derive_tick_array_pda(Pubkey.from_string(whirlpool_addr), start_upper)
    print(f"\npda_lower: {pda_lower}")
    print(f"pda_upper: {pda_upper}")

    if str(pda_lower) == str(pda_upper):
        raw_lower = raw_upper = get_account_bytes(str(pda_lower))
    else:
        raw_lower, raw_upper = get_multiple_accounts([str(pda_lower), str(pda_upper)])
    print(f"raw_lower is raw_upper (same object)? {raw_lower is raw_upper}")
    print(f"raw_lower == raw_upper (same bytes)? {raw_lower == raw_upper}")
    print(f"raw_lower[0:16] hex: {raw_lower[:16].hex()}")
    print(f"raw_upper[0:16] hex: {raw_upper[:16].hex()}")

    lower_initialized, lower_out_a, lower_out_b = get_tick_fee_growth_outside(raw_lower, tick_lower, start_lower, tick_spacing)
    upper_initialized, upper_out_a, upper_out_b = get_tick_fee_growth_outside(raw_upper, tick_upper, start_upper, tick_spacing)

    debug_scan_all_slots(raw_lower, start_lower, tick_spacing, f"raw_lower (start={start_lower})")
    debug_scan_all_slots(raw_upper, start_upper, tick_spacing, f"raw_upper (start={start_upper})")

    print(f"\n--- Slot alignment check ---")
    print(f"tick_lower={tick_lower}, tick_upper={tick_upper}, tick_spacing={tick_spacing}")
    print(f"start_lower={start_lower}, start_upper={start_upper}")
    offset_lower = (tick_lower - start_lower) // tick_spacing
    offset_upper = (tick_upper - start_upper) // tick_spacing
    print(f"offset_in_array: lower={offset_lower}, upper={offset_upper} (must be 0-87)")
    stored_start_lower_in_account = i32_at(raw_lower, 8)
    stored_start_upper_in_account = i32_at(raw_upper, 8)
    print(f"start_tick_index actually stored in lower tick array account: {stored_start_lower_in_account} (expect {start_lower})")
    print(f"start_tick_index actually stored in upper tick array account: {stored_start_upper_in_account} (expect {start_upper})")
    DYNAMIC_TICK_ARRAY_DISCRIMINATOR = bytes([17, 216, 246, 142, 225, 199, 218, 56])
    print(f"lower tick array account size: {len(raw_lower)} bytes (expect 9988 for Fixed)")
    print(f"upper tick array account size: {len(raw_upper)} bytes (expect 9988 for Fixed)")
    print(f"lower discriminator: {list(raw_lower[:8])}, is Dynamic: {raw_lower[:8] == DYNAMIC_TICK_ARRAY_DISCRIMINATOR}")
    print(f"upper discriminator: {list(raw_upper[:8])}, is Dynamic: {raw_upper[:8] == DYNAMIC_TICK_ARRAY_DISCRIMINATOR}")

    fg_inside_a, fg_inside_b = fee_growth_inside(
        tick_current, tick_lower, tick_upper, fg_global_a, fg_global_b,
        lower_initialized, lower_out_a, lower_out_b,
        upper_initialized, upper_out_a, upper_out_b,
    )

    print(f"\n--- Fee growth diagnostic (FIXED: now checking tick.initialized) ---")
    print(f"lower_initialized: {lower_initialized}, upper_initialized: {upper_initialized}")
    print(f"fg_global_a: {fg_global_a}")
    print(f"fg_global_b: {fg_global_b}")
    print(f"lower_out_a: {lower_out_a}, lower_out_b: {lower_out_b}")
    print(f"upper_out_a: {upper_out_a}, upper_out_b: {upper_out_b}")
    print(f"fg_inside_a: {fg_inside_a}")
    print(f"fg_inside_b: {fg_inside_b}")
    print(f"fee_growth_checkpoint_a (on Position): {fee_growth_checkpoint_a}")
    print(f"fee_growth_checkpoint_b (on Position): {fee_growth_checkpoint_b}")
    delta_a_raw = (fg_inside_a - fee_growth_checkpoint_a) % (2 ** 128)
    delta_b_raw = (fg_inside_b - fee_growth_checkpoint_b) % (2 ** 128)
    print(f"delta_a (mod 2^128): {delta_a_raw}")
    print(f"delta_b (mod 2^128): {delta_b_raw}")
    print(f"delta_a / 2^64 (should be small human-scale-ish): {delta_a_raw / Q64}")
    print(f"delta_b / 2^64 (should be small human-scale-ish): {delta_b_raw / Q64}")
    print(f"liquidity: {liquidity}")

    live_owed_a = fee_owed_a + liquidity * ((fg_inside_a - fee_growth_checkpoint_a) % (2 ** 128)) // Q64
    live_owed_b = fee_owed_b + liquidity * ((fg_inside_b - fee_growth_checkpoint_b) % (2 ** 128)) // Q64

    sqrt_price = sqrt_price_raw / Q64
    sqrt_lower = tick_to_sqrt_price(tick_lower)
    sqrt_upper = tick_to_sqrt_price(tick_upper)
    amt_a_raw, amt_b_raw = amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, liquidity)

    # SOL = 9 decimals, USDC = 6 decimals — well-known, but let's fetch to confirm
    dec_a = rpc_call("getAccountInfo", [token_mint_a, {"encoding": "jsonParsed"}])["value"]["data"]["parsed"]["info"]["decimals"]
    dec_b = rpc_call("getAccountInfo", [token_mint_b, {"encoding": "jsonParsed"}])["value"]["data"]["parsed"]["info"]["decimals"]

    amount_a = amt_a_raw / (10 ** dec_a)
    amount_b = amt_b_raw / (10 ** dec_b)
    live_fee_a = live_owed_a / (10 ** dec_a)
    live_fee_b = live_owed_b / (10 ** dec_b)

    price = (sqrt_price ** 2) * (10 ** (dec_a - dec_b))

    print(f"Confirmed decimals: token_a(SOL)={dec_a}, token_b(USDC)={dec_b}")
    print(f"Current price (USDC per SOL): {price:.4f}")
    print(f"Holdings: {amount_a:.6f} SOL + {amount_b:.6f} USDC")
    print(f"Live uncollected fees: {live_fee_a:.8f} SOL + {live_fee_b:.6f} USDC")
    print(f"\nEstimated value at price {price:.2f}: {amount_a * price + amount_b:.2f} USD (compare to screenshot's $19.57)")
    print(f"Estimated fee value: {live_fee_a * price + live_fee_b:.4f} USD (compare to screenshot's $0.44)")


def debug_scan_all_slots(raw, start_tick, tick_spacing, label):
    print(f"\n--- Full slot scan: {label} ---")
    init_count = 0
    for slot in range(88):
        off = 44 + slot * 113
        initialized = raw[off] != 0
        if initialized:
            init_count += 1
            lg = u128_at(raw, off + 1 + 16)
            fg_a = u128_at(raw, off + 1 + 16 + 16)
            implied_tick = start_tick + slot * tick_spacing
            print(f"  slot {slot} (tick {implied_tick}): INITIALIZED, liquidity_gross={lg}, fee_growth_outside_a={fg_a}")
    print(f"Total initialized slots: {init_count} / 88")
    print("Raw fee_growth_outside_a for first 5 slots (regardless of initialized):")
    for slot in range(5):
        off = 44 + slot * 113
        fg_a = u128_at(raw, off + 1 + 16 + 16)
        print(f"  slot {slot}: fee_growth_outside_a={fg_a}")


if __name__ == "__main__":
    main()
