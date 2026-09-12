import os
from web3 import Web3
from eth_abi import decode

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))

PANCAKE_NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
PANCAKE_FACTORY = Web3.to_checksum_address("0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865")

POSITIONS_ABI = [{"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "positions",
    "outputs": [
        {"internalType": "uint96", "name": "nonce", "type": "uint96"},
        {"internalType": "address", "name": "operator", "type": "address"},
        {"internalType": "address", "name": "token0", "type": "address"},
        {"internalType": "address", "name": "token1", "type": "address"},
        {"internalType": "uint24", "name": "fee", "type": "uint24"},
        {"internalType": "int24", "name": "tickLower", "type": "int24"},
        {"internalType": "int24", "name": "tickUpper", "type": "int24"},
        {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
        {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
        {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
        {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
        {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"},
    ], "stateMutability": "view", "type": "function"}]

GET_POOL_ABI = [{"inputs": [
    {"internalType": "address", "name": "tokenA", "type": "address"},
    {"internalType": "address", "name": "tokenB", "type": "address"},
    {"internalType": "uint24", "name": "fee", "type": "uint24"}],
    "name": "getPool", "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
    "stateMutability": "view", "type": "function"}]

import sys
token_id = int(sys.argv[1])

npm = w3.eth.contract(address=PANCAKE_NPM, abi=POSITIONS_ABI)
pos = npm.functions.positions(token_id).call()
print("positions() result:", pos)
token0, token1, fee = pos[2], pos[3], pos[4]

factory = w3.eth.contract(address=PANCAKE_FACTORY, abi=GET_POOL_ABI)
pool_address = factory.functions.getPool(token0, token1, fee).call()
print("pool_address:", pool_address)

# Raw eth_call to slot0(), no ABI decode assumptions
selector = Web3.keccak(text="slot0()")[:4]
raw = w3.eth.call({"to": pool_address, "data": selector})
print(f"raw length: {len(raw)} bytes ({len(raw)//32} words)")
print("raw hex:", raw.hex())

# Try decoding as the standard 7-field shape
try:
    decoded = decode(['uint160','int24','uint16','uint16','uint16','uint32','bool'], raw)
    print("Decoded as 7-field (uint32 feeProtocol):", decoded)
except Exception as e:
    print("7-field decode failed:", e)
