"""Verify pool.liquidity() works correctly across all 3 pool types
against real known positions, before building the APR feature on it."""
import os
from web3 import Web3
import vfat_adapter as va

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
print(f"Connected: {w3.is_connected()}, block {w3.eth.block_number}")

LIQUIDITY_ABI = [{"inputs": [], "name": "liquidity",
    "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
    "stateMutability": "view", "type": "function"}]

cases = [
    ("Uniswap V3 (5992616)", va.UNISWAP_V3_NPM, va.UNISWAP_V3_FACTORY, va.UNISWAP_POOL_ABI, 5992616, va.fetch_position),
    ("PancakeSwap V3 (2121660)", va.PANCAKE_V3_NPM, va.PANCAKE_V3_FACTORY, va.PANCAKE_POOL_ABI, 2121660, va.fetch_position),
]

for label, npm, factory, pool_abi, tid, fetch_fn in cases:
    print(f"\n--- {label} ---")
    pos = fetch_fn(w3, tid, npm, factory, pool_abi)
    pool_addr = pos["pool_address"]
    print(f"pool_address: {pool_addr}, your liquidity: {pos['liquidity']}")
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=LIQUIDITY_ABI)
    try:
        pool_liquidity = pool.functions.liquidity().call()
        share = pos['liquidity'] / pool_liquidity if pool_liquidity else 0
        print(f"pool.liquidity() = {pool_liquidity}")
        print(f"your share of active liquidity: {share*100:.4f}%")
        if pos['liquidity'] > pool_liquidity:
            print("WARNING: your liquidity exceeds pool total — something's wrong (wrong ABI or position out of range)")
    except Exception as e:
        print(f"FAILED: {e}")

print(f"\n--- Aerodrome Slipstream (75410120, unstaked) ---")
pos = va.fetch_position_aerodrome(w3, 75410120)
pool_addr = pos["pool_address"]
print(f"pool_address: {pool_addr}, your liquidity: {pos['liquidity']}")
pool = w3.eth.contract(address=Web3.to_checksum_address(pool_addr), abi=LIQUIDITY_ABI)
try:
    pool_liquidity = pool.functions.liquidity().call()
    share = pos['liquidity'] / pool_liquidity if pool_liquidity else 0
    print(f"pool.liquidity() = {pool_liquidity}")
    print(f"your share of active liquidity: {share*100:.4f}%")
    if pos['liquidity'] > pool_liquidity:
        print("WARNING: your liquidity exceeds pool total — something's wrong")
except Exception as e:
    print(f"FAILED: {e}")
