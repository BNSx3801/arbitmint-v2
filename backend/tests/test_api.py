from __future__ import annotations

import asyncio
import json
from typing import cast
from urllib.parse import urlencode

import pytest

from arbitmint import app as app_module
from arbitmint.market_data import QuoteUnavailable


@pytest.fixture
def reset_asset_cache() -> None:
    app_module._asset_cache = None


def get(path: str, params: dict[str, str] | None = None) -> tuple[int, dict[str, object]]:
    messages: list[dict[str, object]] = []
    raw_path = path.encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": urlencode(params or {}).encode(),
        "headers": [],
        "client": ("test", 123),
        "server": ("test", 80),
    }
    asyncio.run(app_module.app(scope, receive, send))  # type: ignore[arg-type]
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")["body"]
    return int(cast(int, start["status"])), json.loads(cast(bytes, body))


def test_health_identifies_read_only_service() -> None:
    status, body = get("/health")
    assert status == 200
    assert body == {"status": "ok", "mode": "read-only-market-data"}


def test_assets_returns_empty_instead_of_synthetic_pairs(
    reset_asset_cache: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "load_pools", dict)
    monkeypatch.setattr(app_module, "discover_assets", lambda pools: [])
    status, body = get("/api/market/assets")
    assert status == 200
    assert body == {"assets": [], "refresh_interval_ms": 2500}


def test_assets_fail_closed_when_source_is_unavailable(
    reset_asset_cache: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module, "load_pools", lambda: (_ for _ in ()).throw(QuoteUnavailable("offline"))
    )
    status, body = get("/api/market/assets")
    assert status == 503
    assert "offline" in body["detail"]  # type: ignore[operator]


@pytest.mark.parametrize("params", [{"asset": "WETH", "amount_usdc": "NaN"}])
def test_quote_rejects_invalid_request_without_fallback(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, str]
) -> None:
    monkeypatch.setattr(
        app_module, "get_quote", lambda *_: (_ for _ in ()).throw(ValueError("invalid amount"))
    )
    status, body = get("/api/market/quote", params)
    assert status == 422
    assert "invalid amount" in body["detail"]  # type: ignore[operator]


def test_quote_source_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module,
        "get_quote",
        lambda *_: (_ for _ in ()).throw(RuntimeError("https://user:secret@rpc.invalid/api-key")),
    )
    status, body = get(
        "/api/market/quote", {"asset": "WETH", "amount_usdc": "100"}
    )
    assert status == 503
    assert "secret" not in str(body)
    assert "api-key" not in str(body)
