# Test environment

**Date:** 2026-10-15. Local checks use repository lockfiles and installed toolchains. Environment values and credentials are not copied into this report.

| Component | Environment | Notes |
|---|---|---|
| OS / shell | macOS, zsh | Workspace `/Users/bns/Whateva/arbitmint` |
| Solidity | Foundry 1.8.5; solc 0.8.26 | OpenZeppelin 5.4.0 and Uniswap v4-core 4.0.0 in `contracts/lib` |
| Python | Python 3.12; uv-managed `.venv` | FastAPI, SQLAlchemy, web3.py; tests use SQLite in-memory |
| JS | Node 24.20.0, pnpm via Corepack | Next.js 15 / React 19 / Vitest 3; production build tested |
| API test transport | Direct ASGI invocation | `httpx2` is absent, so Starlette TestClient could not load; no new dependency was added |
| Production | Vercel multi-service deployment | `/api/market/assets` observed to return `assets: []`; quote journey unavailable without configured pools |
| External sources | Binance public Spot REST and Unichain Mainnet public RPC | No public-chain transaction made; source APIs were mocked in deterministic unit tests |

## Reproduction commands

From the repo root:

```sh
cd contracts && forge build && forge test -vvv && forge coverage
cd backend && uv run pytest -q && uv run ruff check . && uv run mypy .
cd frontend && pnpm typecheck && pnpm lint && pnpm test && pnpm build
```

Foundry emits warnings that it cannot create its signature cache under `~/.foundry/cache` in this sandbox. Compilation and tests still complete. `forge coverage` also emits many source-anchor warnings; treat its coverage values as indicative rather than precise branch coverage.

## Configuration and test data

- `UNISWAP_V4_POOLS_JSON` is empty by default; do not fill it with unverified addresses.
- Mainnet read-only quote RPC: public Unichain endpoint unless overridden by `UNICHAIN_RPC_URL`.
- Contract orchestration is explicitly Unichain Sepolia (1301); this is separate from read-only quote chain 130.
- WalletConnect project identifier is a public client identifier in ignored local environment config; no private key is required for quote tests.
- All test sale/settlement amounts are integer base units; local test database rows are disposable.
