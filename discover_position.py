"""
Step 2 of discovery: find the actual tokenId of the Uniswap V3 NFT held
by the Sickle (confirmed to exist in discover.py — balanceOf == 1), and
pull its real position data.

The NPM is NOT ERC721Enumerable (no tokenOfOwnerByIndex), so we can't
just index into "the sickle's Nth token." Instead: scan Transfer event
logs where to == sickle_address to find every tokenId ever sent there,
then confirm CURRENT ownership via ownerOf() for each candidate — a
past Transfer-to doesn't mean still-owned-by if it moved again since.

Run with: python discover_position.py <wallet_address>
Requires: ALCHEMY_BASE env var.
"""

import os
import sys
from web3 import Web3

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")

UNISWAP_V3_NPM = Web3.to_checksum_address("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1")
SICKLE_FACTORY = Web3.to_checksum_address("0x71D234A3e1dfC161cc1d081E6496e76627baAc31")

SICKLE_FACTORY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "sickles",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# Standard ERC721 Transfer event + ownerOf, plus Uniswap V3's positions()
NPM_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": True, "internalType": "uint256", "name": "tokenId", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "positions",
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
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

ERC20_MIN_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]


def main():
    if len(sys.argv) != 2:
        print("Usage: python discover_position.py <wallet_address>")
        sys.exit(1)
    wallet = Web3.to_checksum_address(sys.argv[1])

    if not ALCHEMY_BASE:
        print("ERROR: ALCHEMY_BASE not set.")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    if not w3.is_connected():
        print("ERROR: could not connect to Base.")
        sys.exit(1)

    factory = w3.eth.contract(address=SICKLE_FACTORY, abi=SICKLE_FACTORY_ABI)
    sickle_address = factory.functions.sickles(wallet).call()
    print(f"Sickle address: {sickle_address}")

    npm = w3.eth.contract(address=UNISWAP_V3_NPM, abi=NPM_ABI)

    # Scan Transfer events where to == sickle_address, from the NPM's
    # genesis block on Base forward. Base Uniswap V3 NPM was deployed
    # well after Base mainnet launch, but to be safe and avoid an
    # unbounded/expensive full-chain scan, start from a recent-ish
    # block and widen only if nothing is found — printed clearly either
    # way so a bad assumption here is visible, not silent.
    latest_block = w3.eth.block_number
    lookback_blocks = 20_000_000  # generously covers Base's history at ~2s/block
    from_block = max(0, latest_block - lookback_blocks)

    print(f"Scanning Transfer events on NPM to={sickle_address} from block {from_block} to {latest_block} ...")
    transfer_event = npm.events.Transfer()
    try:
        logs = transfer_event.get_logs(from_block=from_block, to_block=latest_block, argument_filters={"to": sickle_address})
    except Exception as e:
        print(f"FAILED to get logs: {e}")
        print("This RPC provider may not support the block range or filter used — may need chunked queries.")
        sys.exit(1)

    candidate_ids = sorted(set(log["args"]["tokenId"] for log in logs))
    print(f"Found {len(candidate_ids)} candidate tokenId(s) ever transferred to this Sickle: {candidate_ids}")

    if not candidate_ids:
        print("No Transfer events found. Either the lookback window is too short, or something")
        print("about the discovery approach is wrong. Stopping rather than guessing further.")
        sys.exit(1)

    # Confirm CURRENT ownership — a past transfer-to doesn't mean still-held.
    current_ids = []
    for tid in candidate_ids:
        owner = npm.functions.ownerOf(tid).call()
        print(f"  tokenId {tid}: current owner = {owner} {'(MATCH)' if owner == sickle_address else '(moved on)'}")
        if owner == sickle_address:
            current_ids.append(tid)

    print(f"\nCurrently held: {current_ids}")
    if len(current_ids) != 1:
        print(f"WARNING: expected exactly 1 (balanceOf said 1 earlier), got {len(current_ids)}.")
        print("Something doesn't add up — investigate before trusting this further.")

    for tid in current_ids:
        print(f"\n--- Position data for tokenId {tid} ---")
        pos = npm.functions.positions(tid).call()
        (nonce, operator, token0, token1, fee, tick_lower, tick_upper,
         liquidity, fee_growth0, fee_growth1, tokens_owed0, tokens_owed1) = pos

        t0 = w3.eth.contract(address=Web3.to_checksum_address(token0), abi=ERC20_MIN_ABI)
        t1 = w3.eth.contract(address=Web3.to_checksum_address(token1), abi=ERC20_MIN_ABI)
        sym0, dec0 = t0.functions.symbol().call(), t0.functions.decimals().call()
        sym1, dec1 = t1.functions.symbol().call(), t1.functions.decimals().call()

        print(f"Pair: {sym0}/{sym1}  fee tier: {fee/10000}%")
        print(f"Tick range: [{tick_lower}, {tick_upper}]")
        print(f"Liquidity: {liquidity}")
        print(f"tokensOwed (as of last touch, NOT live — needs feeGrowthGlobal/Outside calc for real-time): "
              f"{tokens_owed0 / (10**dec0)} {sym0} / {tokens_owed1 / (10**dec1)} {sym1}")


if __name__ == "__main__":
    main()
