"""
vfat-tracker discovery script — NOT the app yet.

Purpose: verify, against real on-chain state, the two things we can't
confirm from a sandbox with no RPC access:
  1. Does SickleFactory.sickles(wallet) resolve to a real Sickle contract?
  2. Does that Sickle directly hold the Uniswap V3 position NFT (per the
     user's claim), or is it staked via a connector/gauge like the
     Aerodrome position turned out to be?

This is deliberately noisy/verbose — every step prints what it did and
what it found, so a wrong assumption surfaces immediately instead of
silently producing plausible-looking garbage.

Run with: python discover.py <wallet_address>
Requires: ALCHEMY_BASE env var (Base RPC URL).
"""

import os
import sys
from web3 import Web3

ALCHEMY_BASE = os.environ.get("ALCHEMY_BASE", "")

# Verified against Uniswap's own official deployments doc
# (docs.uniswap.org/contracts/v3/reference/deployments/base-deployments)
# AND cross-checked on BaseScan: 924,002 transactions, clearly the live
# canonical contract. NOT the "...34f9" address that appears in old
# project notes — that address has zero findable on-chain activity and
# is very likely a typo.
UNISWAP_V3_NPM = Web3.to_checksum_address("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1")
UNISWAP_V3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")

# UNVERIFIED — user-supplied, not independently confirmed by us. This
# script's whole job is to sanity-check this before anything is built
# on top of it.
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

# Minimal ABI — just enough to check balance and, if balanceOf > 0,
# warn that we still need event-log scanning to actually enumerate
# tokenIds (NPM is NOT ERC721Enumerable, confirmed from its verified
# source on BaseScan — no tokenOfOwnerByIndex).
ERC721_MINIMAL_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def main():
    if len(sys.argv) != 2:
        print("Usage: python discover.py <wallet_address>")
        sys.exit(1)
    wallet = Web3.to_checksum_address(sys.argv[1])

    if not ALCHEMY_BASE:
        print("ERROR: ALCHEMY_BASE env var not set. Cannot proceed without a real RPC connection.")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(ALCHEMY_BASE))
    if not w3.is_connected():
        print("ERROR: could not connect to Base via ALCHEMY_BASE. Check the RPC URL.")
        sys.exit(1)
    print(f"Connected to Base. Latest block: {w3.eth.block_number}")

    # ── Step 1: resolve the Sickle address ──────────────────────────
    print(f"\n--- Step 1: resolving Sickle for wallet {wallet} ---")
    print(f"Calling sickles({wallet}) on factory {SICKLE_FACTORY} ...")

    factory = w3.eth.contract(address=SICKLE_FACTORY, abi=SICKLE_FACTORY_ABI)
    try:
        sickle_address = factory.functions.sickles(wallet).call()
    except Exception as e:
        print(f"FAILED: call reverted or errored: {e}")
        print("This means either the factory address is wrong, or the ABI/function")
        print("signature doesn't match what's actually deployed there. Stopping —")
        print("nothing downstream can be trusted until this resolves.")
        sys.exit(1)

    if sickle_address == "0x0000000000000000000000000000000000000000":
        print("FAILED: sickles() returned the zero address.")
        print("Either this wallet has no Sickle deployed on Base, or the factory")
        print("address is wrong. Stopping.")
        sys.exit(1)

    print(f"Resolved Sickle address: {sickle_address}")

    code = w3.eth.get_code(sickle_address)
    if len(code) == 0:
        print(f"WARNING: {sickle_address} has no bytecode — it's an EOA, not a contract.")
        print("This strongly suggests the SickleFactory address is wrong.")
        sys.exit(1)
    print(f"Confirmed: {sickle_address} has {len(code)} bytes of bytecode (it's a real contract).")

    # ── Step 2: check where the Uniswap V3 NFT actually sits ────────
    print(f"\n--- Step 2: checking Uniswap V3 NFT balance ---")
    npm = w3.eth.contract(address=UNISWAP_V3_NPM, abi=ERC721_MINIMAL_ABI)

    print(f"Calling balanceOf({sickle_address}) on NPM {UNISWAP_V3_NPM} ...")
    try:
        sickle_balance = npm.functions.balanceOf(sickle_address).call()
    except Exception as e:
        print(f"FAILED: balanceOf call reverted: {e}")
        sys.exit(1)
    print(f"Sickle's direct NFT balance on the NPM: {sickle_balance}")

    print(f"Calling balanceOf({wallet}) on NPM (in case it's held by the EOA instead) ...")
    try:
        wallet_balance = npm.functions.balanceOf(wallet).call()
    except Exception as e:
        print(f"FAILED: {e}")
        wallet_balance = None
    print(f"Wallet's direct NFT balance on the NPM: {wallet_balance}")

    print("\n--- Result ---")
    if sickle_balance and sickle_balance > 0:
        print(f"CONFIRMED: Sickle directly holds {sickle_balance} Uniswap V3 NFT(s).")
        print("Matches the 'not staked, direct Sickle/NPM route' claim.")
        print("Next step: since NPM has no tokenOfOwnerByIndex (not ERC721Enumerable),")
        print("we'll need Transfer event logs (to=sickle_address) to find the actual")
        print("tokenId(s), then call positions(tokenId) on each to confirm current owner")
        print("and pull range/liquidity/fee data.")
    elif wallet_balance and wallet_balance > 0:
        print("UNEXPECTED: the NFT is held by the raw wallet, not the Sickle at all.")
        print("The 'held through Sickle/NPM route' framing doesn't match on-chain reality —")
        print("worth double-checking with the user before building around the Sickle path.")
    else:
        print("NEITHER the Sickle nor the wallet directly holds a Uniswap V3 NFT.")
        print("Two likely explanations: (a) it's staked in a connector/gauge contract")
        print("we haven't identified yet, same pattern as the Aerodrome position, or")
        print("(b) the SickleFactory address resolved to the wrong Sickle.")
        print("Do NOT assume direct holding from here — needs event-log investigation.")


if __name__ == "__main__":
    main()
