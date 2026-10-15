# QA test plan

## Goal and boundary

Validate the current no-trade quote estimator and separately exercise the experimental run modules and accounting contract. Keep API estimates, simulator outputs, operator-reported settlement, and confirmed chain state distinct. All tests use local fakes, in-memory SQLite or local EVM doubles; no public-chain transaction or wallet signature is part of this plan.

## Test layers

1. **Static/build:** Solidity build and Forge lint; backend Ruff and strict mypy; frontend lint, typecheck, build.
2. **Unit:** integer USDC parsing, order-book level consumption, fee arithmetic, simulator depth/fee/spread/price movement, state transition validation, funding status normalization, evidence calculations, and contract limits/accounting.
3. **API integration:** drive FastAPI as ASGI; validate health, empty asset discovery, source unavailability, invalid parameters, and sanitized upstream failures. This avoids a missing `httpx2` test dependency.
4. **Persistence/idempotency:** durable run/transition records, simulator replay, settlement intent and transaction hash, event cursor and duplicate delivery, provider request idempotency.
5. **Contract integration:** local `PoolManager` double exercises the actual unlock/callback ABI and accounting path; validate minimum output, settlement, zero proceeds, and claim backing. It is not a v4 implementation or fork test.
6. **Frontend:** current Vitest SSR disclosure test, lint, typecheck and production build. Browser E2E, wallet QR, mobile wallet, account/network-change flows remain unverified.
7. **External/system:** public RPC and Binance behavior, source freshness, Vercel live quote and pool configuration, deployed testnet contracts, reorg recovery, and load/concurrency are environment-dependent and not treated as passing by local tests.

## Planned cases and observed status

| Area | Required cases | Status |
|---|---|---|
| Market data | integer amounts; partial bid fills; insufficient depth; pair/pool mapping; fee and P/L sign; invalid/stale source behavior | Unit coverage present; Binance upstream timestamp freshness is blocked by REST response semantics |
| API | health; empty configured pools; upstream outage; invalid request; generic unexpected exception | Added, passing |
| Backend state | idempotent creation; conflicting keys; legal/illegal transitions; non-float evidence; user scoping | Existing suite passes; restart/power-loss and concurrent DB races not exercised |
| Funding | provider gate; intent before side effect; metadata allowlist; independently checked balance; unsupported chain/token | Added selected coverage, passing; no real provider exists |
| Simulator | deterministic config/input capture; fee/spread/depth; failure; same-result retry; changed replay | Added, passing |
| Events | confirmation-depth wait; journal once; state update; cursor | Added, passing; canonical reorg/reversal absent |
| Settlement | durable intent; timeout; evidence validation; confirmed loss/profit accounting; idempotent result | Added, passing including zero-proceeds fix; real Sepolia receipt unavailable |
| Contracts | roles, run uniqueness, swap output/minimum, unused principal, proceeds accounting, backed claim, loss shortfall | 7 local EVM tests passing; Hook has 0% coverage and actual v4 fork is blocked |
| Frontend | initial disclosure, unavailable state and WalletConnect affordance | 1 SSR test passing; interactions/browser workflows untested |
| Reliability/performance | quote load and latency percentiles, concurrency, retry storms, upstream outage and recovery | Not run; no benchmark harness or production-safe representative environment |

## Release gates

- No generated quote fallback or unlabelled estimate: local API and UI tests pass.
- No claim credit beyond backed USDC: contract path and invariant assertion pass locally.
- No run settlement without confirmed simulator record and chain evidence: coordinator tests pass locally.
- Live quote requires at least one independently verified full PoolKey and active Binance pair, plus a source freshness strategy that can detect stale upstream book data. **Not met in production.**
- Testnet execution release additionally requires deployed manifest, hook address permission proof, real PoolManager fork/integration tests, verified provider flow, and end-to-end transaction evidence. **Not met.**

## Exclusions

No mainnet writes, real funds, venue orders, private-key use, or public testnet transactions. No hardware-wallet, provider QR, load test, or cloud database migration exercise was performed.
