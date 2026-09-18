"""
Compare a ~10%-wide concentrated range (matching the user's own real
position: width 10.1%) across the current pool vs the two candidates
identified earlier (Uniswap 0.05%, Aerodrome Slipstream WETH/USDC).

Reuses vfat_adapter's own verified _amounts_for_liquidity and
_tick_to_sqrt_price directly rather than re-deriving the price math by
hand — caught a real inversion bug in an earlier draft by checking
fetch_position's own exact pattern before trusting a rewrite.
"""
import os
import math
from web3 import Web3
import vfat_adapter as va

BASE_RPC = os.environ.get("ALCHEMY_BASE")
w3 = Web3(Web3.HTTPProvider(BASE_RPC))

MIN_POOL_ABI = va.UNISWAP_POOL_ABI + [{
    "inputs": [], "name": "tickSpacing",
    "outputs": [{"internalType": "int24", "name": "", "type": "int24"}],
    "stateMutability": "view", "type": "function",
}]

WETH_DECIMALS, USDC_DECIMALS = 18, 6
TARGET_USD = 243.0
RANGE_PCT = 0.101

CANDIDATES = [
    ("Your current pool: Uniswap V3 0.30%", "0x6c561B446416E1A00E8E93E221854d6eA4171372", 0.003),
    ("Uniswap V3 0.05%", "0xd0b53d9277642d899df5c87a3966a349a798f224", 0.0005),
    ("Aerodrome Slipstream 0.05%", "0x3fe04a59ebd38cf06080a6f60a98d124eb59392a", 0.0005),
]

results = []
for label, pool_address, fee_fraction in CANDIDATES:
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=MIN_POOL_ABI)
    slot0 = pool.functions.slot0().call()
    sqrt_price_x96, current_tick = slot0[0], slot0[1]
    active_liquidity = pool.functions.liquidity().call()
    tick_spacing = pool.functions.tickSpacing().call()

    sqrt_price = sqrt_price_x96 / (2 ** 96)  # raw, matches fetch_position exactly
    decimal_adjustment = 10 ** (WETH_DECIMALS - USDC_DECIMALS)
    weth_price_usd = (sqrt_price ** 2) * decimal_adjustment  # verified formula from fetch_position

    price_now = weth_price_usd
    price_lower_target = price_now * (1 - RANGE_PCT)
    price_upper_target = price_now * (1 + RANGE_PCT)
    # Convert human USDC-per-WETH price bounds back to raw ticks (inverse
    # of fetch_position's current_price = (sqrt_price**2) * decimal_adjustment)
    raw_lower = price_lower_target / decimal_adjustment
    raw_upper = price_upper_target / decimal_adjustment
    tick_lower_raw = math.log(raw_lower) / math.log(1.0001 ** 1) if raw_lower > 0 else 0
    tick_upper_raw = math.log(raw_upper) / math.log(1.0001 ** 1) if raw_upper > 0 else 0
    tick_lower = int(round(tick_lower_raw / tick_spacing)) * tick_spacing
    tick_upper = int(round(tick_upper_raw / tick_spacing)) * tick_spacing

    sqrt_lower = va._tick_to_sqrt_price(tick_lower)
    sqrt_upper = va._tick_to_sqrt_price(tick_upper)

    # Per-unit-liquidity amounts (liquidity=1), then scale to target USD —
    # exact reuse of the already-verified function, no hand-derived inverse.
    amt0_per_l, amt1_per_l = va._amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, 1)
    usd_per_l = (amt0_per_l / (10 ** WETH_DECIMALS)) * weth_price_usd + (amt1_per_l / (10 ** USDC_DECIMALS))
    new_liquidity = TARGET_USD / usd_per_l if usd_per_l > 0 else 0

    share = new_liquidity / (active_liquidity + new_liquidity) if (active_liquidity + new_liquidity) > 0 else 0

    print(f"\n{label} ({pool_address})")
    print(f"  weth_price_usd={weth_price_usd:.2f}, current_tick={current_tick}, tick_spacing={tick_spacing}")
    print(f"  active_liquidity={active_liquidity}, computed_range=[{tick_lower}, {tick_upper}]")
    print(f"  your hypothetical liquidity units for ${TARGET_USD}: {new_liquidity:.0f}")
    print(f"  your share of active liquidity: {share*100:.4f}%")
    results.append((label, share, fee_fraction))

print("\n=== Fetch each pool's real 24h volume and compute your resulting APR ===")
import app as vfat_app
for label, share, fee_fraction in results:
    pool_address = next(addr for lbl, addr, _ in CANDIDATES if lbl == label)
    try:
        candles = vfat_app.get_pool_volume_usd(pool_address, 1, "base")
        daily_volume_usd = candles[-1]["volume_usd"] if candles else None
    except Exception as e:
        print(f"{label}: volume fetch failed ({e})")
        continue
    if daily_volume_usd is None:
        print(f"{label}: no volume data available")
        continue
    daily_pool_fees_usd = daily_volume_usd * fee_fraction
    your_daily_fees_usd = daily_pool_fees_usd * share
    apr_pct = (your_daily_fees_usd / TARGET_USD) * 365 * 100
    print(f"{label}: 24h_volume=${daily_volume_usd:,.0f}, your_share={share*100:.4f}%, resulting APR={apr_pct:.1f}%")
