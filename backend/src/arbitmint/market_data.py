"""Read-only market quotes from Binance Spot and Uniswap v4 on Unichain."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

from web3 import Web3

BINANCE_BASE_URL = "https://data-api.binance.vision"
UNICHAIN_RPC = "https://mainnet.unichain.org"
UNISWAP_V4_QUOTER = Web3.to_checksum_address("0x333e3c607b141b18ff6de9f258db6e77fe7491e0")
USDC_DECIMALS = 6
MAX_INPUT_BASE_UNITS = 2**128 - 1
MAX_ORDERBOOK_LEVELS = 100

QUOTER_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "quoteExactInputSingle",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "params",
                "type": "tuple",
                "components": [
                    {
                        "name": "poolKey",
                        "type": "tuple",
                        "components": [
                            {"name": "currency0", "type": "address"},
                            {"name": "currency1", "type": "address"},
                            {"name": "fee", "type": "uint24"},
                            {"name": "tickSpacing", "type": "int24"},
                            {"name": "hooks", "type": "address"},
                        ],
                    },
                    {"name": "zeroForOne", "type": "bool"},
                    {"name": "exactAmount", "type": "uint128"},
                    {"name": "hookData", "type": "bytes"},
                ],
            }
        ],
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "gasEstimate", "type": "uint256"},
        ],
    }
]


class QuoteUnavailable(ValueError):
    """A quote cannot be produced from fresh, configured sources."""


@dataclass(frozen=True)
class PoolConfig:
    symbol: str
    cex_symbol: str
    token_address: str
    token_decimals: int
    usdc_address: str
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    hook_data: bytes = b""

    @classmethod
    def from_json(cls, symbol: str, value: dict[str, Any]) -> PoolConfig:
        if not re.fullmatch(r"[A-Z0-9]{2,20}", symbol):
            raise ValueError("pool asset symbol is invalid")
        if not isinstance(value, dict):
            raise TypeError(f"{symbol} pool configuration must be an object")
        required = {"chain_id", "token_address", "token_decimals", "usdc_address", "pool_key"}
        missing = required - value.keys()
        if missing:
            raise ValueError(f"{symbol} pool configuration is missing: {', '.join(sorted(missing))}")
        if value.get("chain_id") != 130:
            raise ValueError(f"{symbol} pool must be configured for Unichain Mainnet (130)")
        key = value.get("pool_key")
        if not isinstance(key, dict):
            raise TypeError(f"{symbol} requires a complete pool_key")
        key_fields = {"currency0", "currency1", "fee", "tick_spacing", "hooks"}
        missing_key_fields = key_fields - key.keys()
        if missing_key_fields:
            raise ValueError(
                f"{symbol} pool_key is missing: {', '.join(sorted(missing_key_fields))}"
            )
        cex_symbol = str(value.get("cex_symbol", symbol)).upper()
        if not re.fullmatch(r"[A-Z0-9]{2,20}", cex_symbol):
            raise ValueError(f"{symbol} Binance symbol mapping is invalid")
        token_address = Web3.to_checksum_address(value["token_address"])
        currency0 = Web3.to_checksum_address(key["currency0"])
        currency1 = Web3.to_checksum_address(key["currency1"])
        usdc_address = Web3.to_checksum_address(value["usdc_address"])
        if currency0.lower() >= currency1.lower():
            raise ValueError(f"{symbol} PoolKey currencies must be numerically sorted")
        if token_address.lower() not in {currency0.lower(), currency1.lower()}:
            raise ValueError(f"{symbol} token address is not part of its PoolKey")
        if value.get("token_decimals") not in range(37):
            raise ValueError(f"{symbol} token_decimals must be between 0 and 36")
        if usdc_address.lower() not in {currency0.lower(), currency1.lower()}:
            raise ValueError(f"{symbol} PoolKey must include configured USDC")
        fee = key["fee"]
        spacing = key["tick_spacing"]
        if not isinstance(fee, int) or not 0 <= fee <= 1_000_000:
            raise ValueError(f"{symbol} pool fee must be between 0 and 1000000")
        if not isinstance(spacing, int) or not -(2**23) <= spacing < 2**23:
            raise ValueError(f"{symbol} tick spacing is invalid")
        hook_data_hex = str(value.get("hook_data", "0x"))
        if not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", hook_data_hex):
            raise ValueError(f"{symbol} hook_data must be an even-length 0x-prefixed hex string")
        return cls(
            symbol=symbol,
            cex_symbol=cex_symbol,
            token_address=token_address,
            token_decimals=value["token_decimals"],
            usdc_address=usdc_address,
            currency0=currency0,
            currency1=currency1,
            fee=fee,
            tick_spacing=spacing,
            hooks=Web3.to_checksum_address(key["hooks"]),
            hook_data=bytes.fromhex(hook_data_hex[2:]),
        )

    @property
    def pool_key(self) -> tuple[str, str, int, int, str]:
        return (self.currency0, self.currency1, self.fee, self.tick_spacing, self.hooks)

    @property
    def zero_for_one(self) -> bool:
        return self.currency0.lower() == self.usdc_address.lower()


def load_pools() -> dict[str, PoolConfig]:
    raw = os.getenv("UNISWAP_V4_POOLS_JSON", "{}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("UNISWAP_V4_POOLS_JSON must be valid JSON") from error
    if not isinstance(payload, dict):
        raise TypeError("UNISWAP_V4_POOLS_JSON must be a JSON object")
    return {symbol: PoolConfig.from_json(symbol, config) for symbol, config in payload.items()}


def _request_json(url: str, timeout: float = 8.0) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ArbitMint/0.1 market-data", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise QuoteUnavailable("upstream market-data service is unavailable") from error


def _parse_usdc(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("amount must be a decimal USDC value") from error
    exponent = amount.as_tuple().exponent
    if not amount.is_finite() or amount <= 0 or not isinstance(exponent, int) or exponent < -USDC_DECIMALS:
        raise ValueError("amount must be positive with at most 6 decimal places")
    base_units = int(amount * 10**USDC_DECIMALS)
    if base_units > MAX_INPUT_BASE_UNITS:
        raise ValueError("amount exceeds Uniswap v4 exact-input limit")
    return base_units


def discover_assets(pools: dict[str, PoolConfig]) -> list[dict[str, str]]:
    exchange_info = _request_json(f"{BINANCE_BASE_URL}/api/v3/exchangeInfo?permissions=SPOT")
    eligible: list[dict[str, str]] = []
    configured = {symbol.upper(): pool for symbol, pool in pools.items()}
    for market in exchange_info.get("symbols", []):
        if (
            market.get("status") == "TRADING"
            and market.get("quoteAsset") == "USDC"
            and market.get("baseAsset") in {pool.cex_symbol for pool in configured.values()}
            and market.get("symbol") == f"{market.get('baseAsset')}USDC"
        ):
            eligible.append(
                {
                    "symbol": _frontend_symbol(configured, market["baseAsset"]),
                    "name": _frontend_symbol(configured, market["baseAsset"]),
                    "pair": market["symbol"],
                }
            )
    return sorted(eligible, key=lambda item: item["symbol"])


def _frontend_symbol(pools: dict[str, PoolConfig], cex_symbol: str) -> str:
    return next(symbol for symbol, pool in pools.items() if pool.cex_symbol == cex_symbol)


def _quote_v4(pool: PoolConfig, amount_in: int) -> tuple[int, int, int, datetime]:
    rpc_url = os.getenv("UNICHAIN_RPC_URL", UNICHAIN_RPC)
    usdc_address = Web3.to_checksum_address(
        os.getenv("UNICHAIN_USDC_ADDRESS", "0x078d782b760474a361dda0af3839290b0ef57ad6")
    )
    if usdc_address.lower() != pool.usdc_address.lower() or usdc_address.lower() not in {pool.currency0.lower(), pool.currency1.lower()}:
        raise QuoteUnavailable("configured v4 pool does not contain Unichain USDC")
    if pool.zero_for_one != (pool.currency0.lower() == usdc_address.lower()):
        raise QuoteUnavailable("configured pool direction is inconsistent")
    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
    if not web3.is_connected():
        raise QuoteUnavailable("Unichain Mainnet RPC is unavailable")
    chain_id = web3.eth.chain_id
    if chain_id != 130:
        raise QuoteUnavailable("configured RPC is not Unichain Mainnet (chain ID 130)")
    contract = web3.eth.contract(address=UNISWAP_V4_QUOTER, abi=QUOTER_ABI)
    amount_out, gas_estimate = contract.functions.quoteExactInputSingle(
        (pool.pool_key, pool.zero_for_one, amount_in, pool.hook_data)
    ).call()
    block = web3.eth.get_block("latest")
    block_time = datetime.fromtimestamp(block["timestamp"], UTC)
    max_block_age_seconds = int(os.getenv("UNICHAIN_MAX_BLOCK_AGE_SECONDS", "60"))
    if max_block_age_seconds < 1 or (datetime.now(UTC) - block_time).total_seconds() > max_block_age_seconds:
        raise QuoteUnavailable("Unichain quote block is stale")
    if int(amount_out) <= 0:
        raise QuoteUnavailable("Uniswap v4 returned no output for this exact-input quote")
    return int(amount_out), int(gas_estimate), int(block["number"]), block_time


def _market_sale(pool: PoolConfig, token_amount: int) -> tuple[int, int, datetime]:
    pair = f"{pool.cex_symbol}USDC"
    encoded_pair = urllib.parse.quote(pair)
    payload = _request_json(
        f"{BINANCE_BASE_URL}/api/v3/depth?symbol={encoded_pair}&limit={MAX_ORDERBOOK_LEVELS}"
    )
    received_at = datetime.now(UTC)
    if "bids" not in payload:
        raise QuoteUnavailable(f"Binance does not provide an order book for {pair}")
    token_remaining = Decimal(token_amount) / (10**pool.token_decimals)
    proceeds_usdc = Decimal(0)
    for price_text, quantity_text in payload["bids"]:
        price = Decimal(price_text)
        quantity = Decimal(quantity_text)
        fill = min(token_remaining, quantity)
        proceeds_usdc += fill * price
        token_remaining -= fill
        if token_remaining <= 0:
            break
    if token_remaining > 0:
        raise QuoteUnavailable("Binance bid depth is insufficient to price the full v4 output")
    gross_base_units = int((proceeds_usdc * 10**USDC_DECIMALS).to_integral_value(rounding=ROUND_DOWN))
    return gross_base_units, int(payload.get("lastUpdateId", 0)), received_at


def get_quote(symbol: str, amount: str, pools: dict[str, PoolConfig] | None = None) -> dict[str, Any]:
    normalized_symbol = symbol.upper()
    pool_map = pools if pools is not None else load_pools()
    pool = pool_map.get(normalized_symbol)
    if pool is None:
        raise QuoteUnavailable(f"no configured Uniswap v4 pool for {normalized_symbol}/USDC")
    amount_in = _parse_usdc(amount)
    amount_out, gas_estimate, block_number, block_time = _quote_v4(pool, amount_in)
    gross_sale, orderbook_update_id, book_received_at = _market_sale(pool, amount_out)
    try:
        taker_fee_bps = int(os.getenv("BINANCE_TAKER_FEE_BPS", "10"))
    except ValueError as error:
        raise QuoteUnavailable("BINANCE_TAKER_FEE_BPS must be an integer") from error
    if not 0 <= taker_fee_bps <= 10_000:
        raise QuoteUnavailable("BINANCE_TAKER_FEE_BPS must be between 0 and 10000")
    fee = gross_sale * taker_fee_bps // 10_000
    net_sale = gross_sale - fee
    pnl = net_sale - amount_in
    fetch_age = max(0.0, (datetime.now(UTC) - book_received_at).total_seconds())
    return {
        "status": "available",
        "classification": "estimated",
        "cost_scope": "pre-gas-pre-transfer-costs",
        "asset": normalized_symbol,
        "pair": f"{normalized_symbol}/USDC",
        "binance_pair": f"{pool.cex_symbol}USDC",
        "amount_in_usdc_base_units": str(amount_in),
        "amount_in_usdc": amount,
        "v4_amount_out_base_units": str(amount_out),
        "v4_amount_out": str(Decimal(amount_out) / 10**pool.token_decimals),
        "token_decimals": pool.token_decimals,
        "binance_gross_sale_usdc_base_units": str(gross_sale),
        "binance_fee_usdc_base_units": str(fee),
        "binance_net_sale_usdc_base_units": str(net_sale),
        "estimated_pnl_usdc_base_units": str(pnl),
        "fee_assumption_bps": taker_fee_bps,
        "fee_assumption_source": "configurable estimate; not user-account-specific",
        "gas_estimate_units": str(gas_estimate),
        "gas_cost_included": False,
        "transfer_costs_included": False,
        "sources": {
            "binance": "Binance Spot public order book",
            "binance_received_at": book_received_at.isoformat(),
            "binance_orderbook_update_id": orderbook_update_id,
            "binance_fetch_age_seconds": fetch_age,
            "binance_source_timestamp_available": False,
            "uniswap": "Uniswap v4 Quoter on Unichain Mainnet",
            "unichain_block_number": block_number,
            "unichain_block_timestamp": block_time.isoformat(),
        },
    }
