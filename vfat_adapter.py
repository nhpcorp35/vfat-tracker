"""
vfat_adapter.py

On-chain fetch logic for vfat/Sickle-held Uniswap V3 positions on Base.

Architecture (all confirmed against real chain state via discover.py /
discover_position.py before this was written):
  - Each wallet has one Sickle per chain: SickleFactory.sickles(wallet).
  - The Sickle directly holds the Uniswap V3 position NFT (no gauge/
    staking connector, for this protocol specifically — Aerodrome's
    Slipstream positions ARE gauge-staked, confirmed via a real
    harvestFor transaction; that's a separate adapter, not this one).
  - The NPM is NOT ERC721Enumerable, so tokenId discovery goes through
    Alchemy's indexed alchemy_getAssetTransfers API, not raw
    eth_getLogs (which is capped at a 10-block range on the free tier
    — confirmed via the provider's own error message).
  - A past Transfer-to doesn't mean still-held: candidates are
    re-checked via ownerOf(), and a burned (fully-closed) position
    reverts there rather than erroring — handled as an expected
    outcome, not a crash.

Fee math: live uncollected fees require feeGrowthGlobal (pool-level)
and feeGrowthOutside (per-tick) in addition to the position's own
feeGrowthInsideLast/tokensOwed — the position struct alone only has
fees as of the last on-chain touch (deposit/withdraw/collect), not
real-time. This mirrors the exact overhaul described in the user's own
lptracker.info project notes (subgraph-based -> direct on-chain RPC,
validated against vfat.io's own displayed values).
"""

from web3 import Web3

UNISWAP_V3_NPM = Web3.to_checksum_address("0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1")
UNISWAP_V3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
PANCAKE_V3_NPM = Web3.to_checksum_address("0x46A15B0b27311cedF172AB29E4f4766fbE7F4364")
PANCAKE_V3_FACTORY = Web3.to_checksum_address("0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865")
SICKLE_FACTORY = Web3.to_checksum_address("0x71D234A3e1dfC161cc1d081E6496e76627baAc31")

# Optimism: Uniswap V3 was deployed at the canonical cross-chain address
# here (unlike Base, which has its own unique deployment) — verified
# against Uniswap's own deploys.md and an independent subgraph docs
# page, both agreeing exactly.
OPTIMISM_UNISWAP_V3_NPM = Web3.to_checksum_address("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")
OPTIMISM_UNISWAP_V3_FACTORY = Web3.to_checksum_address("0x1F98431c8aD98523631AE4a59f267346ea31F984")
# Same canonical cross-chain deployment as Optimism's — Uniswap V3 uses
# this address on mainnet, Optimism, Polygon, and Arbitrum alike.
MAINNET_UNISWAP_V3_NPM = OPTIMISM_UNISWAP_V3_NPM
MAINNET_UNISWAP_V3_FACTORY = OPTIMISM_UNISWAP_V3_FACTORY

# No verified SickleFactory address for Optimism, and no reliable
# discovery mechanism either — Alchemy's enhanced APIs aren't available
# on this chain's free public RPCs, Etherscan's NFT-transfer endpoint
# is paid-only for Optimism, and raw eth_getLogs proved unreliable
# (the same 10,000-block range succeeded once and failed minutes later
# with a different error, on the same public endpoint). Given that, the
# Sickle address and its known position(s) are supplied directly by the
# user (verified independently: 45 bytes of bytecode — a real
# contract — and confirmed via vfat.io's own UI to hold this exact
# tokenId), not derived. Adding a new Optimism position later means
# adding its tokenId here — there's no way to auto-discover it.
OPTIMISM_SICKLE_ADDRESS = Web3.to_checksum_address("0x62aba0f25eb30993b577885b32c1b2a572000573")
OPTIMISM_KNOWN_TOKEN_IDS = {
    "uniswap": [1126993],
}

# Ethereum mainnet: same story as Optimism — no verified SickleFactory
# found (three different "SickleFactory"-source contracts turned up on
# Etherscan; all three reverted on sickles() for this wallet, so none
# of them is it). Rather than keep guessing, derived the Sickle address
# directly: called ownerOf() on the known tokenId itself, which IS the
# custody address — no factory resolution needed at all.
MAINNET_SICKLE_ADDRESS = Web3.to_checksum_address("0x099Dc375859cD0c93125FfEde5158e276C01219f")
MAINNET_KNOWN_TOKEN_IDS = {
    "uniswap": [1357998],
}

# Aerodrome Slipstream (Base) — a genuinely different shape, not just a
# type mismatch like Pancake's. All verified directly against
# aerodrome-finance/slipstream's own GitHub interfaces and cross-checked
# on-chain (discover_aerodrome.py), not assumed:
#   - positions() returns tickSpacing where Uniswap/Pancake return fee —
#     same tuple length, different field. Fee is dynamic per-pool, read
#     separately via fee() — not built here; not needed for value/range.
#   - slot0() has only 6 fields (uint160, int24, uint16, uint16, uint16,
#     bool) — feeProtocol is dropped entirely, not just retyped.
#   - ticks() has 10 fields, not 8 — stakedLiquidityNet inserted right
#     after liquidityNet, and rewardGrowthOutsideX128 inserted right
#     after feeGrowthOutside1X128 (both confirmed from BaseScan's
#     verified source for the SlipStream Quoter contract, which
#     documents the same ICLPool interface).
#   - Positions are NOT uniformly gauge-staked: checked both known
#     tokenIds directly and found one held by the Sickle itself, the
#     other by an actual gauge contract. No single expected owner to
#     check against — existence (not-burned) is the only thing verified
#     for this protocol, not a specific holder.
#   - AERO emissions/rewards are NOT covered here — a separate
#     rewardGrowthGlobalX128 accrual mechanism exists, but only for
#     staked positions in the active tick, which doesn't apply
#     uniformly across even this one wallet's two positions.
# Addresses confirmed from aerodrome-finance/slipstream's own deployment
# table (GitHub), not just a BaseScan label — the "PoolFactory" and
# "PoolImplementation" addresses looked similar enough on BaseScan to
# almost use the wrong one.
AERODROME_NPM = Web3.to_checksum_address("0x827922686190790b37229fd06084350E74485b72")
AERODROME_POOL_FACTORY = Web3.to_checksum_address("0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A")
AERODROME_KNOWN_TOKEN_IDS = [75410120, 75563925]

# Reward/staking contracts for emissions tracking. Both confirmed
# directly against real positions, not assumed:
#   - Pancake: checked ownerOf() on the live position (#2121660) —
#     it's held directly, NOT staked in MasterChefV3. This wiring is
#     ready for if/when it IS staked, but reports not-staked (no
#     pending CAKE) for the current position, correctly.
#   - Aerodrome: token 75563925 is confirmed staked (owner = the real
#     gauge contract), token 75410120 is not (owner = the Sickle
#     itself) — checked directly, not assumed uniform.
PANCAKE_MASTERCHEF_V3 = Web3.to_checksum_address("0xC6A2Db661D5a5690172d8eB0a7DEA2d3008665A3")
CAKE_TOKEN_BASE = Web3.to_checksum_address("0x3055913c90Fcc1a6CE9a358911721eEb942013A1")

MASTERCHEF_V3_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "_tokenId", "type": "uint256"}], "name": "pendingCake",
     "outputs": [{"internalType": "uint256", "name": "reward", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# ICLGauge — confirmed interface from BaseScan's verified source for
# the actual gauge holding token 75563925. earned() mirrors
# MasterChefV3's pendingCake(): a direct pending-reward view, no need
# to reimplement the rewardGrowthInside accrual math ourselves.
AERODROME_GAUGE_ABI = [
    {"inputs": [{"internalType": "address", "name": "account", "type": "address"},
                {"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
     "name": "earned", "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "rewardToken", "outputs": [{"internalType": "address", "name": "", "type": "address"}],
     "stateMutability": "view", "type": "function"},
]

# Both protocols confirmed empirically (not assumed) to hold their NFT
# directly in the Sickle — no gauge/farm staking layer, unlike
# Aerodrome's Slipstream positions (confirmed staked via a real
# harvestFor transaction) or, in principle, a Pancake position staked
# in MasterChefV3 for CAKE (checked directly: this wallet's Pancake
# position has zero MasterChefV3 balance, all balance sits on the NPM).
# PROTOCOLS is assembled further down, once UNISWAP_POOL_ABI and
# PANCAKE_POOL_ABI both exist.

Q128 = 2 ** 128

SICKLE_FACTORY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "sickles",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

NPM_ABI = [
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

FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

UNISWAP_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal0X128",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal1X128",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "int24", "name": "tick", "type": "int24"}],
        "name": "ticks",
        "outputs": [
            {"internalType": "uint128", "name": "liquidityGross", "type": "uint128"},
            {"internalType": "int128", "name": "liquidityNet", "type": "int128"},
            {"internalType": "uint256", "name": "feeGrowthOutside0X128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthOutside1X128", "type": "uint256"},
            {"internalType": "int56", "name": "tickCumulativeOutside", "type": "int56"},
            {"internalType": "uint160", "name": "secondsPerLiquidityOutsideX128", "type": "uint160"},
            {"internalType": "uint32", "name": "secondsOutside", "type": "uint32"},
            {"internalType": "bool", "name": "initialized", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

# PancakeSwap V3's pool declares feeProtocol as uint32, not Uniswap's
# uint8 — confirmed by fetching the raw slot0() bytes and decoding
# both ways rather than assuming the fork kept every field identical.
# Everything else about the pool interface matches.
PANCAKE_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint32", "name": "feeProtocol", "type": "uint32"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
] + UNISWAP_POOL_ABI[1:]  # feeGrowthGlobal0/1X128 and ticks() are identical across both

# Aerodrome Slipstream: positions() has tickSpacing where Uniswap/Pancake
# have fee (same tuple length otherwise) — needs its own NPM_ABI entry
# rather than reusing NPM_ABI's positions().
AERODROME_NPM_ABI = [
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
            {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
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

AERODROME_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
]

AERODROME_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal0X128",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "feeGrowthGlobal1X128",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "int24", "name": "tick", "type": "int24"}],
        "name": "ticks",
        "outputs": [
            {"internalType": "uint128", "name": "liquidityGross", "type": "uint128"},
            {"internalType": "int128", "name": "liquidityNet", "type": "int128"},
            {"internalType": "int128", "name": "stakedLiquidityNet", "type": "int128"},
            {"internalType": "uint256", "name": "feeGrowthOutside0X128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthOutside1X128", "type": "uint256"},
            {"internalType": "uint256", "name": "rewardGrowthOutsideX128", "type": "uint256"},
            {"internalType": "int56", "name": "tickCumulativeOutside", "type": "int56"},
            {"internalType": "uint160", "name": "secondsPerLiquidityOutsideX128", "type": "uint160"},
            {"internalType": "uint32", "name": "secondsOutside", "type": "uint32"},
            {"internalType": "bool", "name": "initialized", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

import functools

# PROTOCOLS/OPTIMISM_PROTOCOLS/MAINNET_PROTOCOLS/CHAINS are assembled at
# the end of this file, once fetch_position and fetch_position_aerodrome
# both exist — they reference those functions directly.

ERC20_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"internalType": "string", "name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
]

_symbol_decimals_cache = {}


def _token_meta(w3, address):
    key = address.lower()
    if key in _symbol_decimals_cache:
        return _symbol_decimals_cache[key]
    c = w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)
    meta = (c.functions.symbol().call(), c.functions.decimals().call())
    _symbol_decimals_cache[key] = meta
    return meta


def resolve_sickle(w3, wallet: str):
    """Returns the Sickle address for a wallet, or None if none deployed."""
    factory = w3.eth.contract(address=SICKLE_FACTORY, abi=SICKLE_FACTORY_ABI)
    addr = factory.functions.sickles(Web3.to_checksum_address(wallet)).call()
    if addr == "0x0000000000000000000000000000000000000000":
        return None
    return addr


def check_known_token_ids(w3, sickle_address: str, npm_address: str, token_ids: list) -> list:
    """For chains with no reliable discovery mechanism (see CHAINS'
    'known' discovery method): confirms each supplied tokenId is still
    held by the given address, same ownerOf()-revert-means-burned
    handling as the dynamic path. Does NOT discover new positions —
    a position not in the supplied list is invisible to this chain
    until someone adds its tokenId."""
    npm = w3.eth.contract(address=npm_address, abi=NPM_ABI)
    current_ids = []
    for tid in token_ids:
        try:
            owner = npm.functions.ownerOf(tid).call()
        except Exception as e:
            if "nonexistent token" in str(e):
                continue  # burned — normal lifecycle, not an error
            raise
        if owner == sickle_address:
            current_ids.append(tid)
    return current_ids


def discover_current_token_ids(w3, sickle_address: str, npm_address: str = UNISWAP_V3_NPM) -> list:
    """Finds tokenIds currently held by the Sickle on the given NFT
    position manager, via Alchemy's indexed transfer API (NOT raw
    eth_getLogs — see module docstring). Confirms current ownership per
    candidate; a burned (fully withdrawn) position is skipped, not an
    error."""
    npm = w3.eth.contract(address=npm_address, abi=NPM_ABI)

    candidate_ids = set()
    page_key = None
    while True:
        params = {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "toAddress": sickle_address,
            "contractAddresses": [npm_address],
            "category": ["erc721"],
            "withMetadata": False,
            "excludeZeroValue": False,
        }
        if page_key:
            params["pageKey"] = page_key
        resp = w3.provider.make_request("alchemy_getAssetTransfers", [params])
        if "error" in resp:
            raise RuntimeError(f"alchemy_getAssetTransfers failed: {resp['error']}")
        for t in resp["result"]["transfers"]:
            token_id_hex = t.get("erc721TokenId")
            if token_id_hex:
                candidate_ids.add(int(token_id_hex, 16))
        page_key = resp["result"].get("pageKey")
        if not page_key:
            break

    current_ids = []
    for tid in sorted(candidate_ids):
        try:
            owner = npm.functions.ownerOf(tid).call()
        except Exception as e:
            if "nonexistent token" in str(e):
                continue  # burned — normal lifecycle, not an error
            raise
        if owner == sickle_address:
            current_ids.append(tid)
    return current_ids


def _tick_to_sqrt_price(tick: int) -> float:
    return 1.0001 ** (tick / 2)


def _amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, liquidity):
    """Standard Uniswap V3 liquidity->amounts math, three regimes
    depending on where current price sits relative to the range."""
    if sqrt_price <= sqrt_lower:
        amount0 = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount1 = 0
    elif sqrt_price < sqrt_upper:
        amount0 = liquidity * (1 / sqrt_price - 1 / sqrt_upper)
        amount1 = liquidity * (sqrt_price - sqrt_lower)
    else:
        amount0 = 0
        amount1 = liquidity * (sqrt_upper - sqrt_lower)
    return amount0, amount1


def _live_fee_growth_inside(current_tick, tick_lower, tick_upper,
                             fee_growth_global0, fee_growth_global1,
                             lower_outside0, lower_outside1,
                             upper_outside0, upper_outside1):
    """Uniswap V3's feeGrowthInside calc — the piece that makes fees
    real-time instead of stale-as-of-last-touch. Mirrors the reference
    implementation (Tick.getFeeGrowthInside).

    Takes feeGrowthOutside values directly rather than a raw ticks()
    tuple — Aerodrome's ticks() has 10 fields in a different order
    than Uniswap/Pancake's 8 (stakedLiquidityNet and
    rewardGrowthOutsideX128 inserted at specific positions, not
    appended), so positional tuple-unpacking here would silently grab
    the wrong fields for that protocol instead of erroring."""

    if current_tick >= tick_lower:
        below0, below1 = lower_outside0, lower_outside1
    else:
        below0 = (fee_growth_global0 - lower_outside0) % Q128
        below1 = (fee_growth_global1 - lower_outside1) % Q128

    if current_tick < tick_upper:
        above0, above1 = upper_outside0, upper_outside1
    else:
        above0 = (fee_growth_global0 - upper_outside0) % Q128
        above1 = (fee_growth_global1 - upper_outside1) % Q128

    inside0 = (fee_growth_global0 - below0 - above0) % Q128
    inside1 = (fee_growth_global1 - below1 - above1) % Q128
    return inside0, inside1


def fetch_position(w3, token_id: int, npm_address: str = UNISWAP_V3_NPM, factory_address: str = UNISWAP_V3_FACTORY,
                    pool_abi: list = UNISWAP_POOL_ABI) -> dict:
    """Full position data for one Uniswap-V3-shaped NFT (works for any
    fork sharing the same NonfungiblePositionManager/Pool interface —
    confirmed for PancakeSwap V3, which is a close fork), including
    LIVE uncollected fees (not just tokensOwed-as-of-last-touch)."""
    npm = w3.eth.contract(address=npm_address, abi=NPM_ABI)
    pos = npm.functions.positions(token_id).call()
    (nonce, operator, token0, token1, fee, tick_lower, tick_upper,
     liquidity, fee_growth_inside0_last, fee_growth_inside1_last,
     tokens_owed0, tokens_owed1) = pos

    sym0, dec0 = _token_meta(w3, token0)
    sym1, dec1 = _token_meta(w3, token1)

    factory = w3.eth.contract(address=factory_address, abi=FACTORY_ABI)
    pool_address = factory.functions.getPool(token0, token1, fee).call()
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=pool_abi)

    slot0 = pool.functions.slot0().call()
    sqrt_price_x96, current_tick = slot0[0], slot0[1]
    sqrt_price = sqrt_price_x96 / (2 ** 96)

    fee_growth_global0 = pool.functions.feeGrowthGlobal0X128().call()
    fee_growth_global1 = pool.functions.feeGrowthGlobal1X128().call()
    lower_tick_data = pool.functions.ticks(tick_lower).call()
    upper_tick_data = pool.functions.ticks(tick_upper).call()
    # Uniswap/Pancake shape: (liquidityGross, liquidityNet, feeGrowthOutside0X128, feeGrowthOutside1X128, ...)
    lower_outside0, lower_outside1 = lower_tick_data[2], lower_tick_data[3]
    upper_outside0, upper_outside1 = upper_tick_data[2], upper_tick_data[3]

    fee_growth_inside0, fee_growth_inside1 = _live_fee_growth_inside(
        current_tick, tick_lower, tick_upper,
        fee_growth_global0, fee_growth_global1,
        lower_outside0, lower_outside1, upper_outside0, upper_outside1,
    )

    # Live uncollected = tokensOwed (as of last touch) + liquidity *
    # growth in feeGrowthInside SINCE that last touch.
    live_owed0 = tokens_owed0 + liquidity * ((fee_growth_inside0 - fee_growth_inside0_last) % Q128) // Q128
    live_owed1 = tokens_owed1 + liquidity * ((fee_growth_inside1 - fee_growth_inside1_last) % Q128) // Q128

    sqrt_lower = _tick_to_sqrt_price(tick_lower)
    sqrt_upper = _tick_to_sqrt_price(tick_upper)
    amt0_raw, amt1_raw = _amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, liquidity)

    decimal_adjustment = 10 ** (dec0 - dec1)
    current_price = (sqrt_price ** 2) * decimal_adjustment
    price_lower = (sqrt_lower ** 2) * decimal_adjustment
    price_upper = (sqrt_upper ** 2) * decimal_adjustment

    in_range = tick_lower <= current_tick < tick_upper

    return {
        "token_id": token_id,
        "pool_address": pool_address,
        "token0": {"address": token0, "symbol": sym0, "decimals": dec0},
        "token1": {"address": token1, "symbol": sym1, "decimals": dec1},
        "fee_tier": fee,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "current_tick": current_tick,
        "in_range": in_range,
        "liquidity": liquidity,
        "amount0": amt0_raw / (10 ** dec0),
        "amount1": amt1_raw / (10 ** dec1),
        "current_price": current_price,
        "price_lower": price_lower,
        "price_upper": price_upper,
        "uncollected_fees0": live_owed0 / (10 ** dec0),
        "uncollected_fees1": live_owed1 / (10 ** dec1),
        "is_staked": False,
        "reward_token_address": None,
        "reward_token_symbol": None,
        "pending_reward": None,
    }


def fetch_position_pancake_with_rewards(w3, token_id: int) -> dict:
    """Wraps fetch_position() with a MasterChefV3 staking check —
    checked directly against the real position (#2121660): it's held
    on the NPM directly right now, NOT staked, so this correctly
    reports is_staked=False / pending_reward=None today. Activates
    automatically (no code change needed) if the position is ever
    staked in MasterChefV3 later — pendingCake() is a direct pending-
    reward view, same pattern as Aerodrome's gauge earned()."""
    p = fetch_position(w3, token_id, PANCAKE_V3_NPM, PANCAKE_V3_FACTORY, PANCAKE_POOL_ABI)

    npm = w3.eth.contract(address=PANCAKE_V3_NPM, abi=NPM_ABI)
    owner = npm.functions.ownerOf(token_id).call()
    if owner == PANCAKE_MASTERCHEF_V3:
        p["is_staked"] = True
        try:
            mc = w3.eth.contract(address=PANCAKE_MASTERCHEF_V3, abi=MASTERCHEF_V3_ABI)
            pending_raw = mc.functions.pendingCake(token_id).call()
            cake_symbol, cake_dec = _token_meta(w3, CAKE_TOKEN_BASE)
            p["reward_token_address"] = CAKE_TOKEN_BASE
            p["reward_token_symbol"] = cake_symbol
            p["pending_reward"] = pending_raw / (10 ** cake_dec)
        except Exception:
            pass  # leave pending_reward as None rather than guess
    return p


def fetch_position_aerodrome(w3, token_id: int, sickle_address: str = None) -> dict:
    """Aerodrome Slipstream position data. Deliberately NOT a call to
    fetch_position() with swapped constants — the shapes genuinely
    differ (tickSpacing vs fee in positions(), a 6-field slot0, a
    10-field ticks() with fields in different positions), verified
    directly against aerodrome-finance/slipstream's own interfaces
    rather than assumed from the Pancake precedent.

    AERO emissions: if sickle_address is given, checks the position's
    current owner — if it's not the Sickle itself, treats the owner as
    a gauge and calls its earned(sickle_address, tokenId) directly
    (mirrors MasterChefV3's pendingCake(), no need to reimplement the
    rewardGrowthGlobalX128 accrual ourselves). Confirmed NOT uniform
    even within this one wallet: token 75563925 is staked, 75410120
    isn't — is_staked and pending_aero reflect each position's actual
    state, not an assumption."""
    npm = w3.eth.contract(address=AERODROME_NPM, abi=AERODROME_NPM_ABI)
    pos = npm.functions.positions(token_id).call()
    (nonce, operator, token0, token1, tick_spacing, tick_lower, tick_upper,
     liquidity, fee_growth_inside0_last, fee_growth_inside1_last,
     tokens_owed0, tokens_owed1) = pos

    sym0, dec0 = _token_meta(w3, token0)
    sym1, dec1 = _token_meta(w3, token1)

    factory = w3.eth.contract(address=AERODROME_POOL_FACTORY, abi=AERODROME_FACTORY_ABI)
    pool_address = factory.functions.getPool(token0, token1, tick_spacing).call()
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=AERODROME_POOL_ABI)

    slot0 = pool.functions.slot0().call()
    sqrt_price_x96, current_tick = slot0[0], slot0[1]
    sqrt_price = sqrt_price_x96 / (2 ** 96)
    dynamic_fee = pool.functions.fee().call()

    fee_growth_global0 = pool.functions.feeGrowthGlobal0X128().call()
    fee_growth_global1 = pool.functions.feeGrowthGlobal1X128().call()
    lower_tick_data = pool.functions.ticks(tick_lower).call()
    upper_tick_data = pool.functions.ticks(tick_upper).call()
    # Aerodrome shape: (liquidityGross, liquidityNet, stakedLiquidityNet,
    # feeGrowthOutside0X128, feeGrowthOutside1X128, rewardGrowthOutsideX128, ...)
    # feeGrowthOutside is at index 3,4 here — NOT 2,3 like Uniswap/Pancake,
    # because stakedLiquidityNet is inserted before it.
    lower_outside0, lower_outside1 = lower_tick_data[3], lower_tick_data[4]
    upper_outside0, upper_outside1 = upper_tick_data[3], upper_tick_data[4]

    fee_growth_inside0, fee_growth_inside1 = _live_fee_growth_inside(
        current_tick, tick_lower, tick_upper,
        fee_growth_global0, fee_growth_global1,
        lower_outside0, lower_outside1, upper_outside0, upper_outside1,
    )

    live_owed0 = tokens_owed0 + liquidity * ((fee_growth_inside0 - fee_growth_inside0_last) % Q128) // Q128
    live_owed1 = tokens_owed1 + liquidity * ((fee_growth_inside1 - fee_growth_inside1_last) % Q128) // Q128

    sqrt_lower = _tick_to_sqrt_price(tick_lower)
    sqrt_upper = _tick_to_sqrt_price(tick_upper)
    amt0_raw, amt1_raw = _amounts_for_liquidity(sqrt_price, sqrt_lower, sqrt_upper, liquidity)

    decimal_adjustment = 10 ** (dec0 - dec1)
    current_price = (sqrt_price ** 2) * decimal_adjustment
    price_lower = (sqrt_lower ** 2) * decimal_adjustment
    price_upper = (sqrt_upper ** 2) * decimal_adjustment

    in_range = tick_lower <= current_tick < tick_upper

    # AERO emissions: only meaningful for a staked position, and only
    # if we know which Sickle staked it. Owner-not-Sickle is our signal
    # that it's in a gauge; earned() reverting (owner isn't actually a
    # valid gauge, or some other edge case) degrades to None rather
    # than crashing the whole position fetch.
    is_staked = False
    pending_reward_raw = None
    reward_token_address = None
    if sickle_address is not None:
        owner = npm.functions.ownerOf(token_id).call()
        if owner != sickle_address:
            is_staked = True
            try:
                gauge = w3.eth.contract(address=owner, abi=AERODROME_GAUGE_ABI)
                pending_reward_raw = gauge.functions.earned(sickle_address, token_id).call()
                reward_token_address = gauge.functions.rewardToken().call()
            except Exception:
                pass  # owner wasn't a gauge implementing this interface, or call reverted

    pending_reward = None
    reward_token_symbol = None
    if pending_reward_raw is not None and reward_token_address is not None:
        reward_token_symbol, reward_dec = _token_meta(w3, reward_token_address)
        pending_reward = pending_reward_raw / (10 ** reward_dec)

    return {
        "token_id": token_id,
        "pool_address": pool_address,
        "token0": {"address": token0, "symbol": sym0, "decimals": dec0},
        "token1": {"address": token1, "symbol": sym1, "decimals": dec1},
        "fee_tier": dynamic_fee,  # dynamic, not a fixed tier — may change between reads
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "current_tick": current_tick,
        "in_range": in_range,
        "liquidity": liquidity,
        "amount0": amt0_raw / (10 ** dec0),
        "amount1": amt1_raw / (10 ** dec1),
        "current_price": current_price,
        "price_lower": price_lower,
        "price_upper": price_upper,
        "is_staked": is_staked,
        "reward_token_address": reward_token_address,
        "reward_token_symbol": reward_token_symbol,
        "pending_reward": pending_reward,
        "uncollected_fees0": live_owed0 / (10 ** dec0),
        "uncollected_fees1": live_owed1 / (10 ** dec1),
    }


def check_known_token_ids_exists_only(w3, npm_address: str, token_ids: list) -> list:
    """For protocols where ownership legitimately varies per position —
    Aerodrome's staked-vs-unstaked split, confirmed directly: one known
    tokenId is held by the Sickle itself, the other by an actual gauge
    contract. No single expected owner to check against, so this only
    verifies the position still exists (ownerOf doesn't revert) rather
    than who holds it."""
    current_ids = []
    npm = w3.eth.contract(address=npm_address, abi=AERODROME_NPM_ABI)
    for tid in token_ids:
        try:
            npm.functions.ownerOf(tid).call()
        except Exception as e:
            if "nonexistent token" in str(e):
                continue  # burned — normal lifecycle, not an error
            raise
        current_ids.append(tid)
    return current_ids


PROTOCOLS = {
    "uniswap": {
        "npm": UNISWAP_V3_NPM, "factory": UNISWAP_V3_FACTORY, "label": "Uniswap V3",
        "discovery": "dynamic",
        "fetch_fn": functools.partial(fetch_position, npm_address=UNISWAP_V3_NPM,
                                       factory_address=UNISWAP_V3_FACTORY, pool_abi=UNISWAP_POOL_ABI),
    },
    "pancake": {
        "npm": PANCAKE_V3_NPM, "factory": PANCAKE_V3_FACTORY, "label": "PancakeSwap V3",
        "discovery": "dynamic",
        "fetch_fn": fetch_position_pancake_with_rewards,
    },
    "aerodrome": {
        "npm": AERODROME_NPM, "factory": AERODROME_POOL_FACTORY, "label": "Aerodrome Slipstream",
        "discovery": "known_exists_only",  # ownership varies (Sickle directly OR a gauge) — see comments above
        "known_token_ids": AERODROME_KNOWN_TOKEN_IDS,
        "fetch_fn": fetch_position_aerodrome,
    },
}

OPTIMISM_PROTOCOLS = {
    "uniswap": {
        "npm": OPTIMISM_UNISWAP_V3_NPM, "factory": OPTIMISM_UNISWAP_V3_FACTORY, "label": "Uniswap V3",
        "discovery": "known_owner_check",
        "known_token_ids": OPTIMISM_KNOWN_TOKEN_IDS["uniswap"],
        "expected_owner": OPTIMISM_SICKLE_ADDRESS,
        "fetch_fn": functools.partial(fetch_position, npm_address=OPTIMISM_UNISWAP_V3_NPM,
                                       factory_address=OPTIMISM_UNISWAP_V3_FACTORY, pool_abi=UNISWAP_POOL_ABI),
    },
}

MAINNET_PROTOCOLS = {
    "uniswap": {
        "npm": MAINNET_UNISWAP_V3_NPM, "factory": MAINNET_UNISWAP_V3_FACTORY, "label": "Uniswap V3",
        "discovery": "known_owner_check",
        "known_token_ids": MAINNET_KNOWN_TOKEN_IDS["uniswap"],
        "expected_owner": MAINNET_SICKLE_ADDRESS,
        "fetch_fn": functools.partial(fetch_position, npm_address=MAINNET_UNISWAP_V3_NPM,
                                       factory_address=MAINNET_UNISWAP_V3_FACTORY, pool_abi=UNISWAP_POOL_ABI),
    },
}

# Each chain resolves its Sickle differently: Base has a verified
# factory (SickleFactory.sickles(wallet)); Optimism and mainnet don't,
# so a fixed known Sickle address is used there instead (see the
# OPTIMISM_*/MAINNET_* comments above) — shown for reference/display,
# not used for per-protocol discovery (each protocol now carries its
# own 'discovery' mode, since Base mixes dynamic protocols with
# Aerodrome's known-exists-only one in the same chain).
CHAINS = {
    "base": {
        "label": "Base",
        "gecko_network": "base",
        "protocols": PROTOCOLS,
        "sickle_resolution": "dynamic",
    },
    "optimism": {
        "label": "Optimism",
        "gecko_network": "optimism",
        "protocols": OPTIMISM_PROTOCOLS,
        "sickle_resolution": "fixed",
        "fixed_sickle_address": OPTIMISM_SICKLE_ADDRESS,
    },
    "mainnet": {
        "label": "Ethereum",
        "gecko_network": "eth",
        "protocols": MAINNET_PROTOCOLS,
        "sickle_resolution": "fixed",
        "fixed_sickle_address": MAINNET_SICKLE_ADDRESS,
    },
}
