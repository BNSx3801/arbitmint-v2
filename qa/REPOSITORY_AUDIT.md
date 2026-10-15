# Repository audit

**Audit date:** 2026-10-15  
**Repository state at audit start:** clean `main` at `03cb124` (`Configure Vercel multi-service deployment`)  
**Scope:** source, configuration, local verification, and the public no-trade deployment. No transactions or public-chain writes were submitted.

## Architecture actually present

- **Frontend:** Next.js App Router, React 19, TypeScript, WalletConnect EthereumProvider and injected-wallet discovery. `DemoDashboard` is a read-only cross-venue quote screen. It refreshes at 2.5 seconds and keeps estimate snapshots in component state only. It does not read balances or submit approvals/signatures/transactions.
- **Quote API:** FastAPI exposes `GET /health`, `GET /api/market/assets`, and `GET /api/market/quote`. Asset discovery intersects configured Unichain Mainnet v4 PoolKeys with active Binance USDC Spot pairs. Quote math uses integer token base units and Decimal book arithmetic. The v4 quote uses the public read-only Unichain RPC; the Binance adapter consumes REST bid levels and applies an assumed taker fee.
- **Experimental orchestration:** SQLAlchemy models, a run state machine, deterministic venue simulator, sandbox funding protocol/adapter, confirmed event listener, and settlement gateway/coordinator exist as Python modules. They are not mounted as mutating API routes and are not connected to the current frontend.
- **Contracts:** Solidity `Arbitrageur` uses AccessControl, Pausable, ReentrancyGuard, SafeERC20, per-run accounting and claim backing. It calls the v4 PoolManager through unlock/callback. `ArbitMintHook` restricts callbacks to beforeSwap/afterSwap permissions and records the observed swap. No deployer, CREATE2 miner, verified deployment manifest, or deployed testnet addresses are present.
- **Deployment:** `vercel.json` routes `/api/*` to the FastAPI service and other paths to Next.js. The production API was observed returning an empty asset list because no pool configuration is supplied. The deployed URL does not currently provide a usable market pair.

## Mismatches and limits found

- README previously described live quote data as locally simulated and listed nonexistent `deployment/` and `scripts/` folders. Both documentation errors were corrected in this audit.
- The current no-trade product direction in PRD v1.1 supersedes older workflow material. Funding, run creation, real v4 execution, venue simulation and claims are experimental modules, not current end-to-end product capabilities.
- The test brief's real testnet wallet-funded journey is outside the current no-spend frontend scope. It remains unverified and must not be described as implemented.
- No configured v4 pools means no assets are eligible and no P/L can be returned in the production deployment.
- Binance REST depth provides `lastUpdateId` but no book event timestamp. The old `binance_freshness_seconds` value measured only local time since response receipt and could not prove source freshness. It is now named `binance_fetch_age_seconds`; the response explicitly says a source timestamp is unavailable. Upstream book staleness remains unresolved.
- The event listener confirms logs before processing and deduplicates their position. It advances a durable cursor and does not revisit/rollback already processed events after a later chain reorganization.
- There are no migration scripts, CI workflows, browser E2E suite, load-test suite, or static dependency audit result in the repository.

## Highest-risk gaps

1. **P1 — no eligible live market:** production currently has no configured PoolKey, so the primary quote journey is unavailable.
2. **P1 — Binance source freshness is not measurable:** REST receive time is not source event time; current implementation cannot satisfy a strict stale-book gate.
3. **P1 — contract/hook integration unverified:** local mock tests cover Arbitrageur unlock accounting, but the real Uniswap v4 PoolManager path, deployed hook permission address, and hook callbacks are not tested.
4. **P1 — listener reorg recovery absent:** confirmed event state can diverge after a reorg because the listener does not re-check historical block hashes or reverse state transitions.
5. **P1 — testnet orchestration has no live verified funding provider or end-to-end deployment:** no funding integration, deploy manifest, testnet addresses, or testnet transaction evidence exists.
6. **P2 — production resilience unknown:** no measured concurrency, rate limiting, load, timeout distribution, or recovery drill.

## Baseline and post-change local health

Initial baseline before added tests/fixes: Foundry 4/4, backend 23/23, frontend 1/1; backend Ruff/mypy and frontend lint/typecheck/build passed. Post-change results are recorded in `FINAL_QA_REPORT.md` and the focused reports. These local results do not verify public RPC, Binance source freshness, the deployed PoolManager path, or end-to-end production UX.
