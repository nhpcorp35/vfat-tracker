"""
Find the real, current Uniswap V3 NFT token ID(s) the Optimism Sickle
owns right now — the hardcoded OPTIMISM_KNOWN_TOKEN_IDS list is stale
after a real rebalance closed the old position and minted a new one.
"""
import os
from web3 import Web3

OPTIMISM_RPC_URLS = [
    os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io"),
    os.environ.get("OPTIMISM_RPC_FALLBACK", "https://optimism.drpc.org"),
]
SICKLE = Web3.to_checksum_address("0x62aba0f25eb30993b577885b32c1b2a572000573")
NPM = Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")

ABI = [
    {"inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "index", "type": "uint256"}],
     "name": "tokenOfOwnerByIndex", "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]

w3 = None
for url in OPTIMISM_RPC_URLS:
    candidate = Web3(Web3.HTTPProvider(url))
    if candidate.is_connected():
        w3 = candidate
        print(f"Connected via {url}")
        break
if w3 is None:
    print("FAILED: no Optimism RPC connected")
    exit(1)

npm = w3.eth.contract(address=NPM, abi=ABI)
balance = npm.functions.balanceOf(SICKLE).call()
print(f"Sickle {SICKLE} currently owns {balance} NFT(s) on Optimism Uniswap V3 NPM")
for i in range(balance):
    token_id = npm.functions.tokenOfOwnerByIndex(SICKLE, i).call()
    print(f"  token_id: {token_id}")
