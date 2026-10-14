from datetime import UTC, datetime
from decimal import Decimal

import pytest

from arbitmint import market_data
from arbitmint.market_data import PoolConfig, QuoteUnavailable


def test_parse_usdc_uses_integer_base_units() -> None:
    assert market_data._parse_usdc("12.345678") == 12_345_678


@pytest.mark.parametrize("amount", ["0", "-1", "1.0000001", "NaN", "Infinity"])
def test_parse_usdc_rejects_invalid_values(amount: str) -> None:
    with pytest.raises(ValueError):
        market_data._parse_usdc(amount)


def test_market_sale_consumes_multiple_bid_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = PoolConfig(
        symbol="WETH",
        cex_symbol="ETH",
        token_address="0x0000000000000000000000000000000000000003",
        token_decimals=18,
        usdc_address="0x0000000000000000000000000000000000000001",
        currency0="0x0000000000000000000000000000000000000001",
        currency1="0x0000000000000000000000000000000000000003",
        fee=500,
        tick_spacing=10,
        hooks="0x0000000000000000000000000000000000000000",
    )
    monkeypatch.setattr(
        market_data,
        "_request_json",
        lambda _url: {
            "lastUpdateId": 42,
            "bids": [["10", "1"], ["9", "2"]],
        },
    )

    proceeds, update_id, received_at = market_data._market_sale(pool, 2 * 10**18)

    assert proceeds == 19_000_000
    assert update_id == 42
    assert received_at.tzinfo is not None


def test_market_sale_fails_when_book_depth_is_short(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = PoolConfig(
        symbol="WETH",
        cex_symbol="ETH",
        token_address="0x0000000000000000000000000000000000000003",
        token_decimals=18,
        usdc_address="0x0000000000000000000000000000000000000001",
        currency0="0x0000000000000000000000000000000000000001",
        currency1="0x0000000000000000000000000000000000000003",
        fee=500,
        tick_spacing=10,
        hooks="0x0000000000000000000000000000000000000000",
    )
    monkeypatch.setattr(market_data, "_request_json", lambda _url: {"bids": [["10", "0.5"]]})

    with pytest.raises(QuoteUnavailable, match="insufficient"):
        market_data._market_sale(pool, 10**18)


def test_pool_config_requires_sorted_complete_v4_key() -> None:
    pool = PoolConfig.from_json(
        "WETH",
        {
            "chain_id": 130,
            "token_address": "0x0000000000000000000000000000000000000003",
            "token_decimals": 18,
            "usdc_address": "0x0000000000000000000000000000000000000001",
            "cex_symbol": "ETH",
            "pool_key": {
                "currency0": "0x0000000000000000000000000000000000000001",
                "currency1": "0x0000000000000000000000000000000000000003",
                "fee": 500,
                "tick_spacing": 10,
                "hooks": "0x0000000000000000000000000000000000000000",
            },
        },
    )
    assert pool.cex_symbol == "ETH"
    assert pool.zero_for_one is True


def test_market_sale_keeps_decimal_arithmetic(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = PoolConfig(
        symbol="TOK",
        cex_symbol="TOK",
        token_address="0x0000000000000000000000000000000000000003",
        token_decimals=6,
        usdc_address="0x0000000000000000000000000000000000000001",
        currency0="0x0000000000000000000000000000000000000001",
        currency1="0x0000000000000000000000000000000000000003",
        fee=500,
        tick_spacing=10,
        hooks="0x0000000000000000000000000000000000000000",
    )
    monkeypatch.setattr(
        market_data,
        "_request_json",
        lambda _url: {"bids": [["1.23456789", "1"]]},
    )

    proceeds, _, _ = market_data._market_sale(pool, 1_000_000)
    assert proceeds == int(Decimal("1.234567") * 1_000_000)


def test_discovery_uses_explicit_cex_symbol_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = PoolConfig(
        symbol="WETH",
        cex_symbol="ETH",
        token_address="0x0000000000000000000000000000000000000003",
        token_decimals=18,
        usdc_address="0x0000000000000000000000000000000000000001",
        currency0="0x0000000000000000000000000000000000000001",
        currency1="0x0000000000000000000000000000000000000003",
        fee=500,
        tick_spacing=10,
        hooks="0x0000000000000000000000000000000000000000",
    )
    monkeypatch.setattr(
        market_data,
        "_request_json",
        lambda _url: {
            "symbols": [
                {"status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDC", "symbol": "ETHUSDC"},
                {"status": "TRADING", "baseAsset": "WETH", "quoteAsset": "USDC", "symbol": "WETHUSDC"},
            ]
        },
    )

    assert market_data.discover_assets({"WETH": pool}) == [
        {"symbol": "WETH", "name": "WETH", "pair": "ETHUSDC"}
    ]


def test_quote_applies_configured_fee_and_never_claims_gas_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = PoolConfig(
        symbol="WETH",
        cex_symbol="ETH",
        token_address="0x0000000000000000000000000000000000000003",
        token_decimals=18,
        usdc_address="0x0000000000000000000000000000000000000001",
        currency0="0x0000000000000000000000000000000000000001",
        currency1="0x0000000000000000000000000000000000000003",
        fee=500,
        tick_spacing=10,
        hooks="0x0000000000000000000000000000000000000000",
    )
    monkeypatch.setenv("BINANCE_TAKER_FEE_BPS", "10")
    monkeypatch.setattr(market_data, "_quote_v4", lambda *_args: (2 * 10**18, 123_000, 99, datetime.now(UTC)))
    monkeypatch.setattr(market_data, "_market_sale", lambda *_args: (2_000_000_000, 123, datetime.now(UTC)))

    result = market_data.get_quote("WETH", "1000", {"WETH": pool})

    assert result["binance_fee_usdc_base_units"] == "2000000"
    assert result["estimated_pnl_usdc_base_units"] == "998000000"
    assert result["gas_cost_included"] is False
    assert result["classification"] == "estimated"
