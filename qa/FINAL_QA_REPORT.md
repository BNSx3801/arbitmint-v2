# Final QA report

**Date:** 2026-10-15  
**Assessment:** local static/unit/integration-style checks plus source review. No public-chain write, trade, wallet signature, or production mutation was performed.

## Decision

**NO-GO for acceptance as a usable live quote MVP or testnet fund-flow MVP.** The production asset list is empty because no verified Uniswap v4 PoolKey is configured; Binance REST book freshness cannot be established from a source event timestamp. Separately, the testnet flow lacks real PoolManager/Hook integration evidence, a deployed permission-checked Hook, and a verified funding provider. The existing deployment can be described only as an unavailable/read-only demo until those gates are closed.

This decision does not imply the live read-only estimator makes trades: it does not. The current frontend has no fund flow. Experimental contracts/backend modules should remain out of the product path until their separate gates pass.

## Verification summary

| Check | Result |
|---|---|
| Backend regression | **41 passed**, 1 third-party `websockets.legacy` deprecation warning |
| Foundry tests | **7 passed, 0 failed, 0 skipped** |
| Foundry build | Passed during test/coverage compile; `forge lint` reports reviewed-but-open warnings |
| Foundry coverage | Arbitrageur 83.95% lines, 30.91% branches; Hook 0%; overall lines 67.92%. Anchor warnings reduce precision. |
| Frontend Vitest | **1 passed** |
| Frontend lint | Passed |
| Frontend typecheck | Passed after QA changes |
| Frontend production build | Passed after Vitest/PostCSS update |
| Ruff / mypy | Passed after final changes |
| Browser E2E | Blocked/not run; no framework and no eligible production market |
| Performance p50/p95/p99 | Not measured |
| Frontend dependency vulnerability scan | Follow-up audit: 1 high advisory remains in lint-only transitive `braces@3.0.3`; upstream lists no patched version. Initial 8 advisories were cleared by Vitest/PostCSS updates. |
| Python dependency vulnerability scan | Not run |

## Changes made during QA

- Added API, deterministic simulator, funding adapter, event listener and settlement test suites.
- Added local PoolManager double tests that exercise the actual Arbitrageur unlock callback and claim backing.
- Fixed simulator same-result replay after SOLD while preserving immutable input/config checks.
- Fixed settlement replay after a completed settlement.
- Allowed zero-proceeds contract settlement and gateway handling so a total loss can be finalized with its shortfall recorded and no claim credit.
- Kept failed/uncertain or inconsistent settlement evidence in a reconciliation-required PENDING intent and did not advance run state.
- Renamed Binance local response age to `binance_fetch_age_seconds`, explicitly stated source timestamp is unavailable, and requested no-cache REST behavior.
- Corrected README scope and repository layout claims; documented the Binance freshness limit in the demo guide.
- Updated Vitest to 4.1.11 and PostCSS to 8.5.30 after npm audit; this cleared two critical, two high and four moderate dependency advisories. One high `braces` advisory has no upstream patch.

## Critical blockers and next actions

1. Configure and independently verify a full Unichain Mainnet PoolKey and active Binance USDC pair. Confirm deployed contracts, token identity/decimals, pool liquidity and quote behavior before enabling the asset.
2. Replace REST receive-time freshness with a timestamped, sequence-checked Binance depth feed or equivalent verifiable source; test stale events, sequence gaps, reconnect and out-of-order updates.
3. Add real v4 fork/integration coverage and Hook CREATE2 deployment tooling with explicit permission-bit assertion; test beforeSwap/afterSwap caller, run context, pool, deltas, callback order and reentrancy.
4. Add Foundry invariant/fuzz tests and independent contract review before any testnet fund-flow release.
5. Define listener reorg recovery and run persistent-database restart/concurrency behavior; add real PostgreSQL integration coverage.
6. Add browser E2E for asset discovery, quote refresh/unavailability, P/L color/sign, wallet optionality and network/account changes.
7. Run dependency vulnerability scanning, quote API rate/concurrency tests, and representative latency benchmarks before setting SLOs.

## Deliverables

This QA package contains all requested reports: repository audit, test plan, traceability, environment, frontend, opportunity engine, contracts, orchestration, E2E, security findings, performance/resilience and final decision.
