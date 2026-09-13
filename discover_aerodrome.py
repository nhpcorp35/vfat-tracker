"""
Aerodrome Slipstream diagnostic — verify before building anything.
Checks: positions() shape (tickSpacing in place of fee, confirmed from
Aerodrome's own GitHub interface), current owner (expected: a gauge,
not the Sickle directly — confirmed architecture from a real
harvestFor tx last night), pool address via the ACTUAL PoolFactory
(not the "PoolImplementation" address that shares a similar BaseScan
label), and the pool's slot0()/feeGrowthGlobal/ticks ABI shape (don't
assume it matches Uniswap's after the Pancake feeProtocol lesson).
"""
import os
from web3 import Web3
from eth_abi import decode

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
print(f"Connected: {w3.is_connected()}, block {w3.eth.block_number}")

AERO_NPM = Web3.to_checksum_address("0x827922686190790b37229fd06084350E74485b72")
AERO_POOL_FACTORY = Web3.to_checksum_address("0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A")
KNOWN_TOKEN_IDS = [75410120, 75563925]

POSITIONS_ABI = [{"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "positions",
    "outputs": [
        {"internalType": "uint96", "name": "nonce", "type": "uint96"},
        {"internalType": "address", "name": "operator", "type": "address"},
        {"internalType": "address", "name": "token0", "type": "address"},
        {"internalType": "address", "name": "token1", "type": "address"},
        {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
        {"internalType": "int24", "name": "tickLower", "type": "int24"},
        {"internalType": "int24", "name": "tickUpper", "type": "int24"},
        {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
        {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
        {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
        {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
        {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"},
    ], "stateMutability": "view", "type": "function"}]

OWNER_OF_ABI = [{"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "ownerOf",
    "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]

GET_POOL_ABI = [{"inputs": [
    {"internalType": "address", "name": "tokenA", "type": "address"},
    {"internalType": "address", "name": "tokenB", "type": "address"},
    {"internalType": "int24", "name": "tickSpacing", "type": "int24"}],
    "name": "getPool", "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
    "stateMutability": "view", "type": "function"}]

npm = w3.eth.contract(address=AERO_NPM, abi=POSITIONS_ABI + OWNER_OF_ABI)
factory = w3.eth.contract(address=AERO_POOL_FACTORY, abi=GET_POOL_ABI)

pool_addresses = set()
for tid in KNOWN_TOKEN_IDS:
    print(f"\n--- Token {tid} ---")
    pos = npm.functions.positions(tid).call()
    (nonce, operator, token0, token1, tick_spacing, tick_lower, tick_upper,
     liquidity, fg0, fg1, owed0, owed1) = pos
    print(f"  token0={token0} token1={token1} tickSpacing={tick_spacing} "
          f"tickLower={tick_lower} tickUpper={tick_upper} liquidity={liquidity}")

    owner = npm.functions.ownerOf(tid).call()
    print(f"  current owner (expected: a gauge, not the wallet/Sickle): {owner}")
    code_len = len(w3.eth.get_code(owner))
    print(f"  owner bytecode length: {code_len} bytes {'(contract)' if code_len > 0 else '(EOA!)'}")

    pool_addr = factory.functions.getPool(token0, token1, tick_spacing).call()
    print(f"  pool address (via ACTUAL PoolFactory): {pool_addr}")
    pool_addresses.add(pool_addr)

print(f"\nUnique pool addresses across both positions: {pool_addresses}")
if len(pool_addresses) == 1:
    print("Same pool for both positions (as expected — both are CL100-WETH/USDC).")

# Now check the pool's slot0()/feeGrowthGlobal/ticks raw bytes — don't
# assume Uniswap's shape.
pool_addr = list(pool_addresses)[0]
print(f"\n--- Raw slot0() check on pool {pool_addr} ---")
selector = Web3.keccak(text="slot0()")[:4]
raw = w3.eth.call({"to": pool_addr, "data": selector})
print(f"raw length: {len(raw)} bytes ({len(raw)//32} words)")
try:
    decoded_u8 = decode(['uint160','int24','uint16','uint16','uint16','uint8','bool'], raw)
    print(f"Decoded as Uniswap-shape (uint8 feeProtocol): {decoded_u8}")
except Exception as e:
    print(f"Uniswap-shape decode failed: {e}")
try:
    decoded_u32 = decode(['uint160','int24','uint16','uint16','uint16','uint32','bool'], raw)
    print(f"Decoded as Pancake-shape (uint32 feeProtocol): {decoded_u32}")
except Exception as e:
    print(f"Pancake-shape decode failed: {e}")

print(f"\n--- feeGrowthGlobal0X128/1X128 check ---")
for fn_name in ["feeGrowthGlobal0X128", "feeGrowthGlobal1X128"]:
    sel = Web3.keccak(text=f"{fn_name}()")[:4]
    try:
        raw_fg = w3.eth.call({"to": pool_addr, "data": sel})
        val = decode(['uint256'], raw_fg)[0]
        print(f"  {fn_name}: {val}")
    except Exception as e:
        print(f"  {fn_name}: FAILED — {e}")

print(f"\n--- ticks(tickLower) check (using first position's tickLower) ---")
tick_check = tick_lower  # from the loop above, last position's value — good enough for shape-checking
sel = Web3.keccak(text="ticks(int24)")[:4]
import eth_abi as eth_abi_mod
encoded_arg = eth_abi_mod.encode(['int24'], [tick_check])
try:
    raw_ticks = w3.eth.call({"to": pool_addr, "data": sel + encoded_arg})
    print(f"raw length: {len(raw_ticks)} bytes ({len(raw_ticks)//32} words)")
except Exception as e:
    print(f"ticks() call FAILED: {e}")
