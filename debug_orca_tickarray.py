"""
Fetch the real TickArray accounts for our confirmed position's tick
bounds, and determine empirically which variant (legacy fixed vs the
newer DynamicTickArray) is actually deployed here — rather than assume.
"""
import os
import hashlib
import base64
import requests
from solders.pubkey import Pubkey

RPC_URL = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
WHIRLPOOL_PROGRAM = Pubkey.from_string("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc")
WHIRLPOOL_ADDRESS = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"  # from previous verified run

TICK_LOWER = -23932
TICK_UPPER = -20912
TICK_SPACING = 4
TICK_ARRAY_SIZE = 88

# Confirmed from carbon-orca-whirlpool-decoder's own source directly
DYNAMIC_TICK_ARRAY_DISCRIMINATOR = bytes([17, 216, 246, 142, 225, 199, 218, 56])


def anchor_discriminator(account_name):
    return hashlib.sha256(f"account:{account_name}".encode()).digest()[:8]


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


def tick_array_start_index(tick_index, tick_spacing):
    ticks_in_array = TICK_ARRAY_SIZE * tick_spacing
    return (tick_index // ticks_in_array) * ticks_in_array  # floor division, matches Rust div_euclid for positive divisor


def derive_tick_array_pda(whirlpool, start_tick_index):
    seeds = [b"tick_array", bytes(whirlpool), str(start_tick_index).encode()]
    pda, bump = Pubkey.find_program_address(seeds, WHIRLPOOL_PROGRAM)
    return pda


def main():
    whirlpool = Pubkey.from_string(WHIRLPOOL_ADDRESS)

    # Candidate discriminators to check against
    candidates = {
        "TickArray (legacy name guess)": anchor_discriminator("TickArray"),
        "FixedTickArray (name guess)": anchor_discriminator("FixedTickArray"),
        "DynamicTickArray (confirmed from decoder source)": DYNAMIC_TICK_ARRAY_DISCRIMINATOR,
    }
    print("Locally computed/known candidate discriminators:")
    for name, disc in candidates.items():
        print(f"  {name}: {list(disc)}")

    for label, tick in [("lower", TICK_LOWER), ("upper", TICK_UPPER)]:
        start_idx = tick_array_start_index(tick, TICK_SPACING)
        pda = derive_tick_array_pda(whirlpool, start_idx)
        print(f"\n--- Tick array for {label} bound (tick={tick}, start_tick_index={start_idx}) ---")
        print(f"PDA: {pda}")
        raw = get_account_bytes(str(pda))
        if raw is None:
            print("FAILED: no account found at that PDA.")
            continue
        print(f"Account size: {len(raw)} bytes")
        actual_disc = raw[0:8]
        print(f"Actual discriminator: {list(actual_disc)}")
        matched = None
        for name, disc in candidates.items():
            if bytes(actual_disc) == bytes(disc):
                matched = name
        print(f"Matches: {matched or 'NONE of our candidates — need to investigate further'}")


if __name__ == "__main__":
    main()
