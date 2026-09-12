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
SICKLE_FACTORY = Web3.to_checksum_address("0x71D234A3e1dfC161cc1d081E6496e76627baAc31")

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

POOL_ABI = [
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


def discover_current_token_ids(w3, sickle_address: str) -> list:
    """Finds tokenIds currently held by the Sickle on the Uniswap V3 NPM,
    via Alchemy's indexed transfer API (NOT raw eth_getLogs — see module
    docstring). Confirms current ownership per candidate; a burned
    (fully withdrawn) position is skipped, not an error."""
    npm = w3.eth.contract(address=UNISWAP_V3_NPM, abi=NPM_ABI)

    candidate_ids = set()
    page_key = None
    while True:
        params = {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "toAddress": sickle_address,
            "contractAddresses": [UNISWAP_V3_NPM],
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
                             lower_tick_data, upper_tick_data):
    """Uniswap V3's feeGrowthInside calc — the piece that makes fees
    real-time instead of stale-as-of-last-touch. Mirrors the reference
    implementation (Tick.getFeeGrowthInside)."""
    (_, _, lower_outside0, lower_outside1, *_rest_l) = lower_tick_data
    (_, _, upper_outside0, upper_outside1, *_rest_u) = upper_tick_data

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


def fetch_position(w3, token_id: int) -> dict:
    """Full position data for one Uniswap V3 NFT, including LIVE
    uncollected fees (not just tokensOwed-as-of-last-touch)."""
    npm = w3.eth.contract(address=UNISWAP_V3_NPM, abi=NPM_ABI)
    pos = npm.functions.positions(token_id).call()
    (nonce, operator, token0, token1, fee, tick_lower, tick_upper,
     liquidity, fee_growth_inside0_last, fee_growth_inside1_last,
     tokens_owed0, tokens_owed1) = pos

    sym0, dec0 = _token_meta(w3, token0)
    sym1, dec1 = _token_meta(w3, token1)

    factory = w3.eth.contract(address=UNISWAP_V3_FACTORY, abi=FACTORY_ABI)
    pool_address = factory.functions.getPool(token0, token1, fee).call()
    pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=POOL_ABI)

    slot0 = pool.functions.slot0().call()
    sqrt_price_x96, current_tick = slot0[0], slot0[1]
    sqrt_price = sqrt_price_x96 / (2 ** 96)

    fee_growth_global0 = pool.functions.feeGrowthGlobal0X128().call()
    fee_growth_global1 = pool.functions.feeGrowthGlobal1X128().call()
    lower_tick_data = pool.functions.ticks(tick_lower).call()
    upper_tick_data = pool.functions.ticks(tick_upper).call()

    fee_growth_inside0, fee_growth_inside1 = _live_fee_growth_inside(
        current_tick, tick_lower, tick_upper,
        fee_growth_global0, fee_growth_global1,
        lower_tick_data, upper_tick_data,
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
    }
