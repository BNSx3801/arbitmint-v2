# Security findings

**Assessment type:** source-level review and local test review; not an independent audit. Severity reflects potential impact if the associated feature were released.

| ID | Severity | Finding | Evidence / effect | Recommended closure |
|---|---|---|---|---|
| SEC-01 | P1 | No configured eligible market in production | Live asset discovery returns an empty list; users cannot obtain the primary estimate | Add only independently verified full PoolKeys; verify token/pool chain and liquidity before enabling |
| SEC-02 | P1 | Binance upstream book freshness cannot be proven | REST depth has no event timestamp; local receive age is not upstream age. Stale response can be mistaken for a current quote | Use timestamped depth stream with sequence-gap/reconnect handling or another verified timestamp source; fail closed on gaps |
| SEC-03 | P1 | Hook deployment and callback security are untested | Hook coverage 0%; CREATE2 permission bits are required; real caller/order/data path untested | Add CREATE2 miner + permission assertion and real v4 fork tests for caller, pool, run ID, callback order and reentry |
| SEC-04 | P1 | Listener has no reorg rollback/reconciliation | Cursor is monotonic; confirmed event’s block hash is not later revalidated | Recheck a configurable finality window and implement auditable rollback/replay before relying on listener state |
| SEC-05 | P1 | Contract accounting lacks fuzzed invariant evidence | Handwritten unit tests pass, but arbitrary sequences and multi-user backing are not property-tested | Add Foundry invariant/fuzz properties for total claim backing, settlement uniqueness, claim reduction and principal shortfall |
| SEC-06 | P1 | Experimental fund flow lacks verified provider/deployment | Funding adapter is gated, but no real sandbox provider, testnet deployment manifest, or end-to-end evidence exists | Keep feature disabled until provider semantics and deployed testnet flow are reviewed and verified |
| SEC-07 | P2 | Public quote API has no rate limiting/load evidence | Browser polls at 2.5 seconds and each quote invokes external data sources; no concurrency or abuse test | Add request budget/cache policy and measure upstream load before expanding availability |
| SEC-08 | P2 | `braces` stack-exhaustion advisory remains in lint tooling | npm audit identifies `braces@3.0.3` through `eslint-config-next > fast-glob > micromatch`; upstream currently lists no patched version | Track upstream; upgrade the dependency chain when a compatible fix is published |

## Positive evidence

- No secrets or private keys were found in tracked source during the scan; local environment files are ignored.
- Current public API is GET-only; no unauthenticated mutating route is exposed.
- Generic quote-source exceptions are sanitized from HTTP response; focused ASGI test verifies a fake credential-bearing exception is not reflected.
- Contract enforces role separation, pause, per-run cap, allowlists and backed claims; 7 local EVM tests pass.
- The UI communicates read-only estimate and no token spend.

## Secret scan scope

Tracked filenames and source were searched for common private key/token patterns without printing matching values. This is a heuristic repository scan, not Git history scanning, a provider secret scan, or a guarantee that credentials were never committed in history.

## Dependency audit

The initial npm audit reported 9 advisories (2 critical, 3 high, 4 moderate), including vulnerable `tinypool`, Vitest mocker, and PostCSS versions. Vitest was upgraded to 4.1.11 and PostCSS pinned to 8.5.30. The follow-up audit reports **1 high advisory** (`braces@3.0.3`) and no critical, moderate, or other high findings. The remaining package is part of the development lint toolchain and npm lists no patched version (`patched versions: <0.0.0`). Python dependency vulnerability scanning was not run.
