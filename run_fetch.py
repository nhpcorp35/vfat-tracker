import os
import sys
from web3 import Web3
import vfat_adapter as va

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")

def main():
    token_id = int(sys.argv[1])
    w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    print(f"Connected: {w3.is_connected()}, block {w3.eth.block_number}")
    pos = va.fetch_position(w3, token_id)
    for k, v in pos.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    main()
