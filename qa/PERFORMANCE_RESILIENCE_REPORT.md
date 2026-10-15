# Performance and resilience report

## Measured data

- Expanded backend suite: **41 passed in 1.58 seconds** in the final local run (pytest-reported duration; includes SQLite and mocked dependencies).
- Foundry 7-test suite completed locally; individual test gas figures are listed in Forge output but are test harness costs, not deployed transaction gas benchmarks.
- No representative quote API, browser, or public upstream latency measurements were made. **p50/p95/p99 are unavailable**; no load/performance claim is made.

## Existing resilience behavior

- Quote source failures raise unavailable errors; API does not substitute generated prices. Unexpected upstream quote exceptions return a generic 503.
- Frontend prevents overlapping quote refresh calls and cancels stale component updates after unmount.
- Settlement timeouts remain uncertain and require reconciliation; transaction hash is journaled before broadcast.
- Funding provider timeouts remain PENDING; provider metadata is allowlisted.
- Listener confirmation depth and unique event position provide basic duplicate/reorg delay protection, but no later reorg reversal exists.

## Unmeasured / unresolved

- No concurrent quote, burst, soak, DB contention, memory, rate-limit, or recovery test.
- Every uncached quote can call both Binance REST and the public Unichain RPC. Public RPC quotas/outage behavior are not characterized.
- Binance REST response time is observable, source book event age is not.
- No Vercel cold-start, timeout, deployment rollback, or production incident/recovery drill was performed.
- No realistic PostgreSQL, queue, or persistent Vercel storage configuration was exercised. Current market API itself does not use the run database.

## Result

**Performance: BLOCKED for a numerical SLO.** Resilience unit cases pass, but workload capacity and percentile latency remain unknown.
