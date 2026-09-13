"""
Backward chunked eth_getLogs search: start at the chain tip, walk back
10,000 blocks at a time, stop as soon as we find a Transfer-to event
for this address+contract. This is a one-time expensive discovery —
once found, the app should cache the tokenId and only re-scan if that
position closes. Capped at ~1 year of lookback so it doesn't run
forever against a wallet with no match.
"""
import time
from web3 import Web3

RPC_URLS = ["https://mainnet.optimism.io", "https://optimism.drpc.org"]
SICKLE_CUSTODY = Web3.to_checksum_address("0x62aba0f25eb30993b577885b32c1b2a572000573")
NPM_OPTIMISM = Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")
CHUNK = 10_000
MAX_LOOKBACK_BLOCKS = 15_768_000  # ~1 year at 2s/block

TRANSFER_ABI = [{
    "anonymous": False,
    "inputs": [
        {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
        {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
        {"indexed": True, "internalType": "uint256", "name": "tokenId", "type": "uint256"},
    ],
    "name": "Transfer", "type": "event",
}]


def get_w3():
    for url in RPC_URLS:
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            return w3
    raise RuntimeError("No RPC available")


def main():
    w3 = get_w3()
    latest = w3.eth.block_number
    print(f"Chain tip: {latest}")
    npm = w3.eth.contract(address=NPM_OPTIMISM, abi=TRANSFER_ABI)
    transfer_event = npm.events.Transfer()

    to_block = latest
    scanned = 0
    start_time = time.time()
    found_ids = set()

    while scanned < MAX_LOOKBACK_BLOCKS:
        from_block = max(0, to_block - CHUNK)
        try:
            logs = transfer_event.get_logs(fromBlock=from_block, toBlock=to_block,
                                            argument_filters={"to": SICKLE_CUSTODY})
        except Exception as e:
            print(f"  [{from_block}-{to_block}] FAILED: {e}")
            break
        if logs:
            for log in logs:
                found_ids.add(log["args"]["tokenId"])
            print(f"  [{from_block}-{to_block}] FOUND: {[l['args']['tokenId'] for l in logs]}")
            break
        scanned += (to_block - from_block)
        to_block = from_block
        if from_block == 0:
            break

    elapsed = time.time() - start_time
    print(f"\nScanned {scanned} blocks in {elapsed:.1f}s")
    print(f"Found tokenIds ever transferred to this address: {sorted(found_ids)}")

    for tid in sorted(found_ids):
        try:
            owner_abi = [{"inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
                          "name": "ownerOf", "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                          "stateMutability": "view", "type": "function"}]
            npm_owner = w3.eth.contract(address=NPM_OPTIMISM, abi=owner_abi)
            owner = npm_owner.functions.ownerOf(tid).call()
            print(f"  tokenId {tid}: current owner = {owner} {'(MATCH — currently held)' if owner == SICKLE_CUSTODY else '(moved on)'}")
        except Exception as e:
            print(f"  tokenId {tid}: ownerOf failed (likely burned): {e}")


if __name__ == "__main__":
    main()
