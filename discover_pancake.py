"""
Diagnostic: is the Pancake V3 position held directly by the Sickle on
the NPM, or staked in MasterChefV3 for CAKE rewards? Checked
empirically, not assumed — same discipline as the Uniswap V3 and
(earlier, informally) Aerodrome checks.
"""
import os
import sys
from web3 import Web3

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")

SICKLE_FACTORY = Web3.to_checksum_address("0x71D234A3e1dfC161cc1d081E6496e76627baAc31")
PANCAKE_NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
PANCAKE_MASTERCHEF_V3 = Web3.to_checksum_address("0xC6A2Db661D5a5690172d8eB0a7DEA2d3008665A3")

SICKLE_FACTORY_ABI = [{"inputs": [{"internalType": "address", "name": "", "type": "address"}], "name": "sickles",
    "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]

ERC721_BALANCE_ABI = [{"inputs": [{"internalType": "address", "name": "owner", "type": "address"}], "name": "balanceOf",
    "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]

MASTERCHEF_ABI = ERC721_BALANCE_ABI + [
    {"inputs": [{"internalType": "address", "name": "owner", "type": "address"}, {"internalType": "uint256", "name": "index", "type": "uint256"}],
     "name": "tokenOfOwnerByIndex", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "_tokenId", "type": "uint256"}], "name": "pendingCake",
     "outputs": [{"internalType": "uint256", "name": "reward", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "name": "userPositionInfos",
     "outputs": [
         {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
         {"internalType": "uint128", "name": "boostLiquidity", "type": "uint128"},
         {"internalType": "int24", "name": "tickLower", "type": "int24"},
         {"internalType": "int24", "name": "tickUpper", "type": "int24"},
         {"internalType": "uint256", "name": "rewardGrowthInside", "type": "uint256"},
         {"internalType": "uint256", "name": "reward", "type": "uint256"},
         {"internalType": "address", "name": "user", "type": "address"},
         {"internalType": "uint256", "name": "pid", "type": "uint256"},
         {"internalType": "uint256", "name": "boostMultiplier", "type": "uint256"},
     ], "stateMutability": "view", "type": "function"},
]

def main():
    wallet = Web3.to_checksum_address(sys.argv[1])
    w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    print(f"Connected: {w3.is_connected()}")

    factory = w3.eth.contract(address=SICKLE_FACTORY, abi=SICKLE_FACTORY_ABI)
    sickle = factory.functions.sickles(wallet).call()
    print(f"Sickle: {sickle}")

    npm = w3.eth.contract(address=PANCAKE_NPM, abi=ERC721_BALANCE_ABI)
    direct_balance = npm.functions.balanceOf(sickle).call()
    print(f"Direct Pancake NPM balance (Sickle): {direct_balance}")

    mc = w3.eth.contract(address=PANCAKE_MASTERCHEF_V3, abi=MASTERCHEF_ABI)
    staked_balance = mc.functions.balanceOf(sickle).call()
    print(f"Staked balance in MasterChefV3 (Sickle): {staked_balance}")

    if staked_balance > 0:
        for i in range(staked_balance):
            tid = mc.functions.tokenOfOwnerByIndex(sickle, i).call()
            info = mc.functions.userPositionInfos(tid).call()
            pending = mc.functions.pendingCake(tid).call()
            print(f"  Staked tokenId {tid}: liquidity={info[0]}, tickLower={info[2]}, tickUpper={info[3]}, "
                  f"pid={info[7]}, user={info[6]}, pendingCake={pending}")

if __name__ == "__main__":
    main()
# re-run trigger 1789256644
