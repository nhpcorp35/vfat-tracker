"""
Optimism diagnostic — checking what we actually have before building
anything. Two things to verify:
  1. Is 0x62aba0f...000573 a real contract, and does it directly hold
     a Uniswap V3 NFT on Optimism (same NPM address as mainnet/Polygon/
     Arbitrum, confirmed earlier via Uniswap's own deploys.md)?
  2. Since Alchemy's alchemy_getAssetTransfers won't work on a public
     RPC, what block range DOES a raw eth_getLogs call tolerate here?
     Testing empirically rather than guessing a chunk size.
"""
import os
from web3 import Web3

RPC_PRIMARY = "https://mainnet.optimism.io"
RPC_FALLBACK = "https://optimism.drpc.org"

SICKLE_CUSTODY = Web3.to_checksum_address("0x62aba0f25eb30993b577885b32c1b2a572000573")
UNISWAP_V3_NPM_OP = Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")

ERC721_BALANCE_ABI = [{"inputs": [{"internalType": "address", "name": "owner", "type": "address"}], "name": "balanceOf",
    "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}]

TRANSFER_EVENT_ABI = [{
    "anonymous": False,
    "inputs": [
        {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
        {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
        {"indexed": True, "internalType": "uint256", "name": "tokenId", "type": "uint256"},
    ],
    "name": "Transfer", "type": "event",
}]


def try_rpc(url):
    print(f"\n=== Trying RPC: {url} ===")
    w3 = Web3(Web3.HTTPProvider(url))
    connected = w3.is_connected()
    print(f"Connected: {connected}")
    if not connected:
        return None
    print(f"Latest block: {w3.eth.block_number}")
    return w3


def main():
    w3 = try_rpc(RPC_PRIMARY)
    if w3 is None:
        print("Primary failed, trying fallback...")
        w3 = try_rpc(RPC_FALLBACK)
    if w3 is None:
        print("BOTH RPCs failed to connect. Stopping.")
        return

    print(f"\n--- Checking Sickle custody address {SICKLE_CUSTODY} ---")
    code = w3.eth.get_code(SICKLE_CUSTODY)
    print(f"Bytecode length: {len(code)} bytes {'(real contract)' if len(code) > 0 else '(EOA — not a contract!)'}")

    npm = w3.eth.contract(address=UNISWAP_V3_NPM_OP, abi=ERC721_BALANCE_ABI)
    try:
        balance = npm.functions.balanceOf(SICKLE_CUSTODY).call()
        print(f"Direct Uniswap V3 NFT balance: {balance}")
    except Exception as e:
        print(f"balanceOf call failed: {e}")

    print(f"\n--- Testing eth_getLogs block range tolerance ---")
    latest = w3.eth.block_number
    npm_events = w3.eth.contract(address=UNISWAP_V3_NPM_OP, abi=TRANSFER_EVENT_ABI)
    transfer_event = npm_events.events.Transfer()
    # Try progressively smaller ranges until one succeeds, to find the
    # actual limit rather than assume one.
    for span in [2_000_000, 500_000, 100_000, 50_000, 10_000, 2_000, 500]:
        from_block = max(0, latest - span)
        try:
            logs = transfer_event.get_logs(fromBlock=from_block, toBlock=latest,
                                            argument_filters={"to": SICKLE_CUSTODY})
            print(f"  span={span} blocks: SUCCESS ({len(logs)} matching logs)")
            break
        except Exception as e:
            msg = str(e)
            print(f"  span={span} blocks: FAILED — {msg[:200]}")


if __name__ == "__main__":
    main()
