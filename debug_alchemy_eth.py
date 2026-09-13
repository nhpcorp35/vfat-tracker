"""
Checks whether the existing ALCHEMY_BASE key also works for Ethereum
mainnet, by swapping the subdomain (base-mainnet -> eth-mainnet) and
testing connectivity. Never prints the actual key.
"""
import os
from web3 import Web3

alchemy_base_url = os.environ.get("ALCHEMY_BASE", "")
if not alchemy_base_url:
    print("ALCHEMY_BASE not set at all.")
    exit(1)

if "base-mainnet" not in alchemy_base_url:
    print(f"ALCHEMY_BASE doesn't match the expected 'base-mainnet' subdomain pattern — "
          f"can't safely derive an eth-mainnet URL from it. URL shape: "
          f"{alchemy_base_url.split('://')[0]}://{'*' * 10}")
    exit(1)

eth_url = alchemy_base_url.replace("base-mainnet", "eth-mainnet")
masked = eth_url.split("/v2/")[0] + "/v2/***"
print(f"Trying: {masked}")

w3 = Web3(Web3.HTTPProvider(eth_url))
try:
    connected = w3.is_connected()
    print(f"Connected: {connected}")
    if connected:
        print(f"Latest Ethereum mainnet block: {w3.eth.block_number}")
        print("RESULT: Same key works for Ethereum mainnet.")
    else:
        print("RESULT: Connected() returned False — key likely doesn't cover this network.")
except Exception as e:
    print(f"RESULT: Failed — {e}")
