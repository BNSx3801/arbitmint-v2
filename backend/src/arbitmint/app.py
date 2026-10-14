"""FastAPI read-only market quote service."""

from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from arbitmint.market_data import QuoteUnavailable, discover_assets, get_quote, load_pools

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

app = FastAPI(title="ArbitMint Market Quote API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
        ).split(",")
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_asset_cache: tuple[float, list[dict[str, str]]] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "read-only-market-data"}


@app.get("/api/market/assets")
def assets() -> dict[str, Any]:
    global _asset_cache
    now = time.monotonic()
    if _asset_cache is None or now - _asset_cache[0] >= 60:
        try:
            _asset_cache = (now, discover_assets(load_pools()))
        except (QuoteUnavailable, ValueError, TypeError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    return {"assets": _asset_cache[1], "refresh_interval_ms": 2500}


@app.get("/api/market/quote")
def quote(
    asset: str = Query(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9]+$"),
    amount_usdc: str = Query(min_length=1, max_length=40),
) -> dict[str, Any]:
    try:
        return get_quote(asset, amount_usdc)
    except QuoteUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:  # Upstream RPC and ABI errors must fail closed.
        raise HTTPException(status_code=503, detail="one or more quote sources are unavailable") from error
