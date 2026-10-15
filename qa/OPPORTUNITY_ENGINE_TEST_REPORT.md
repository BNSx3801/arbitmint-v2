# Opportunity engine and market quote report

## Actual implementation

There is no candidate-size opportunity engine, optimizer, safety-buffer model, oracle sanity check, or GO/NO-GO reason-code API. Current quote code supports one hypothetical USDC size: quote exact input against a configured Uniswap v4 pool, consume Binance bid levels for the output amount, subtract a configured fee estimate, and return estimated P/L before gas and transfer costs.

## Test evidence

- Existing market tests cover integer USDC parsing, partial fills across book levels, insufficient depth, PoolKey validation/sorting, explicit CEX symbol mapping, decimal arithmetic, fee application and cost disclosure.
- New ASGI/API tests cover empty eligible assets, upstream source failure, invalid quote input, and sanitized generic RPC/API exception behavior.
- Backend regression: **41 passed** in the current run.
- No network request or quote was used as test oracle; upstream calls are mocked.

## Findings

- Production eligible assets are empty because no verified PoolKey config exists.
- Binance depth REST responses expose `lastUpdateId` but not an event timestamp. `binance_fetch_age_seconds` measures local response-receipt age only; the API now states `binance_source_timestamp_available: false`. A true stale-book gate needs a timestamped feed such as a correctly maintained depth WebSocket stream.
- Current P/L excludes gas, bridging, withdrawals, transfer costs, execution latency/risk and user-specific CEX fees. `gas_estimate_units` is not a gas price or gas cost.
- Chainlink and GO/NO-GO logic are not part of the current estimator and must not be reported as satisfied.

## Result

**Partial pass** for deterministic quote calculations and fail-closed errors. Live eligibility and strict source freshness are release blockers for a usable live quote service.
