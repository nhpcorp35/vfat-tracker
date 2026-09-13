"""
Multiple contracts matching SickleFactory's source turned up on
Etherscan for mainnet — testing each directly against the known
wallet + known NFT (#1357998) rather than guessing which is real.
"""
import os
from web3 import Web3

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")
eth_url = ALCHEMY_BASE.replace("base-mainnet", "eth-mainnet")
w3 = Web3(Web3.HTTPProvider(eth_url))
print(f"Connected: {w3.is_connected()}, block {w3.eth.block_number}")

WALLET = Web3.to_checksum_address("0xc33Fc161686ED2B8649162Ff9BfC3ED3a7f24801")
NPM_MAINNET = Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")
KNOWN_TOKEN_ID = 1357998

CANDIDATES = [
    "0x8a09b9784e19de39bf40106726541c6c09eec40d",
    "0xe569386bd22245cc8bd706dbbcb9ca503e4624e9",
    "0x5b8ee344996220a9983856ff74d7dee937ea8715",
]

SICKLE_FACTORY_ABI = [{"inputs": [{"internalType": "address", "name": "", "type": "address"}], "name": "sickles",
    "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]

OWNER_OF_ABI = [{"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}], "name": "ownerOf",
    "outputs": [{"internalType": "address", "name": "", "type": "address"}], "stateMutability": "view", "type": "function"}]

npm = w3.eth.contract(address=NPM_MAINNET, abi=OWNER_OF_ABI)
actual_owner = npm.functions.ownerOf(KNOWN_TOKEN_ID).call()
print(f"\nActual current owner of NFT #{KNOWN_TOKEN_ID}: {actual_owner}")

for addr in CANDIDATES:
    addr = Web3.to_checksum_address(addr)
    print(f"\n--- Trying candidate factory {addr} ---")
    code = w3.eth.get_code(addr)
    print(f"  Bytecode: {len(code)} bytes")
    factory = w3.eth.contract(address=addr, abi=SICKLE_FACTORY_ABI)
    try:
        sickle = factory.functions.sickles(WALLET).call()
        print(f"  sickles({WALLET}) = {sickle}")
        if sickle == actual_owner:
            print(f"  *** MATCH: this factory resolves to the actual NFT owner! ***")
        elif sickle == "0x0000000000000000000000000000000000000000":
            print(f"  (zero address — this wallet has no Sickle from this factory)")
        else:
            print(f"  (resolved to a different address than the actual NFT owner)")
    except Exception as e:
        print(f"  FAILED: {e}")
