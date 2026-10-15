# Requirements traceability

Status is against the current PRD v1.1 no-trade direction unless marked **experimental**. “Partial” means a local component exists but the complete requirement is not demonstrated.

| Requirement | Implementation/evidence | Status | Gap / risk |
|---|---|---|---|
| G1 eligible asset and momentary estimated P/L | `market_data.py`, `DemoDashboard.tsx`, unit quote tests | Partial | Requires explicit PoolKey; production asset list is empty. Binance event timestamp absent. |
| G2 optional informational Sepolia wallet; no spend | Dashboard injected/WalletConnect displays address/network; SSR disclosure test | Partial | No browser E2E for real wallet adapters; feature availability depends on public project ID. |
| G3 no synthetic fallback; disclose estimate | API returns unavailable; UI labels read-only estimate; API tests ensure generic failure and no synthetic response | Pass locally | Live upstream freshness cannot be proven for Binance REST depth. |
| G4 reproducible setup and scope | README, `.env.example`, workspace manifests | Partial | No CI, no browser E2E, no verified pool configuration. |
| FR-1.1 v4 exact-input quote (experimental/quotes) | `market_data._quote_v4` | Partial | Public RPC endpoint; no configured pool or live quote in deployment. |
| FR-1.2 Chainlink freshness | Not present in current quote direction | Not applicable to current no-trade flow | Historical PRD section retained; Chainlink is not used by current estimator. |
| FR-1.3–1.6 opportunity engine / GO-NO-GO | No opportunity engine or GO/NO-GO API | Not implemented | Current product only estimates one entered size. |
| FR-2 funding/provider verification (experimental) | Provider Protocol and gated `FundingAdapter`; tests assert default gate | Partial | No Circle client; no verified provider workflow or deployment secret configuration. |
| FR-3.1 exact-input v4 callback | `Arbitrageur.executeArbitrage` and `unlockCallback`; local manager double | Partial | Real PoolManager fork/integration and deployed Sepolia validation absent. |
| FR-3.2–3.9 contract controls/accounting | AccessControl, pause, allowlists, SafeERC20, accounting, refunds, backed claims; 7 tests | Partial | Hook not tested; fuzz/invariant suite absent; deployment and operator controls unverified. |
| FR-3.10–3.15 Hook constraints | `ArbitMintHook` source | Not verified | 0% hook coverage; CREATE2 address miner/manifest missing; caller/order/permission integration not tested. |
| FR-4 durable state and side effects (experimental) | SQLAlchemy models, repository, intent modules; local tests | Partial | Not wired to current market API; DB migrations/restart and concurrent production DB tests absent. |
| FR-5 dashboard live no-spend quote | Dashboard source + SSR test | Partial | Asset flow unavailable on production due zero pools; no browser test. |
| FR-6 API (current) | FastAPI GET routes and new ASGI tests | Partial | No source freshness guarantee or load/rate-limit verification. |
| E2E quote journey | No browser automation suite | Blocked | No configured live pool and no Playwright/browser test setup. |
