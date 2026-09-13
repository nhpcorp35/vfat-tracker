"""Does the user's Pancake WETH/USDC pool have an active CAKE farm at
all? Checking directly rather than guessing why the position isn't
staked."""
import os
from web3 import Web3

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))

import vfat_adapter as va

TOKEN_ID = 2121660
npm = w3.eth.contract(address=va.PANCAKE_V3_NPM, abi=va.NPM_ABI)
pos = npm.functions.positions(TOKEN_ID).call()
token0, token1, fee = pos[2], pos[3], pos[4]
factory = w3.eth.contract(address=va.PANCAKE_V3_FACTORY, abi=va.FACTORY_ABI)
pool_address = factory.functions.getPool(token0, token1, fee).call()
print(f"Pool address: {pool_address}")

MASTERCHEF_ABI = [
    {"inputs": [{"internalType": "address", "name": "", "type": "address"}], "name": "v3PoolAddressPid",
     "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "name": "poolInfo",
     "outputs": [
         {"internalType": "uint256", "name": "allocPoint", "type": "uint256"},
         {"internalType": "address", "name": "v3Pool", "type": "address"},
         {"internalType": "address", "name": "token0", "type": "address"},
         {"internalType": "address", "name": "token1", "type": "address"},
         {"internalType": "uint24", "name": "fee", "type": "uint24"},
         {"internalType": "uint256", "name": "totalLiquidity", "type": "uint256"},
         {"internalType": "uint256", "name": "totalBoostLiquidity", "type": "uint256"},
     ], "stateMutability": "view", "type": "function"},
]

mc = w3.eth.contract(address=va.PANCAKE_MASTERCHEF_V3, abi=MASTERCHEF_ABI)
pid = mc.functions.v3PoolAddressPid(pool_address).call()
print(f"v3PoolAddressPid: {pid}")

pool_info = mc.functions.poolInfo(pid).call()
print(f"poolInfo(pid={pid}): allocPoint={pool_info[0]}, v3Pool={pool_info[1]}")

if pool_info[1].lower() != pool_address.lower():
    print(f"\nRESULT: pid {pid} does NOT correspond to this pool (default zero-value — "
          f"poolInfo(0) points to a different/no pool). This pool has NO registered farm at all.")
elif pool_info[0] == 0:
    print(f"\nRESULT: This pool DOES have a registered farm (pid {pid}), but allocPoint is 0 — "
          f"no active CAKE emissions right now, even if you staked.")
else:
    print(f"\nRESULT: This pool has an ACTIVE farm (pid {pid}, allocPoint={pool_info[0]}) — "
          f"staking would earn CAKE. It's just not staked yet.")
