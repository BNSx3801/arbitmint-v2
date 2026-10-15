# Backend orchestration report

## Scope and wiring

FastAPI's current HTTP app is read-only and exposes health, eligible assets, and quotes only. SQLAlchemy run/funding/simulator/event/settlement modules are not exposed as API routes and do not back the dashboard's local estimate snapshot. Default DB config is SQLite; there are no schema migrations.

## Verification

- Baseline: 23 backend tests passed.
- Expanded local suite: **41 passed**, including new ASGI route behavior, deterministic simulator, funding gate/order, event confirmation/cursor/deduplication, and settlement accounting/uncertainty tests.
- Ruff and strict mypy are scheduled to be re-run after this report's latest additions.

## Verified protections

- Run creation uses idempotency keys, validates addresses/chain/amounts, persists CREATED and transition evidence together before any subsequent adapter side effect.
- Funding adapter requires an explicitly verified provider capability, restricts chain 1301/tokens, persists a CREATED record before provider request, filters response metadata and requires an independent on-chain balance before FUNDED.
- Simulator stores the complete deterministic configuration and captured inputs. This audit fixed same-result replay after SOLD; changing config or acquired quantity remains rejected.
- Settlement persists intent before gateway call, records transaction hash before broadcast, reconciles timeout as uncertain, validates confirmed accounting/backing evidence and stores transition history. This audit fixed zero proceeds and completed-result replay ordering.
- Event listener waits for its configured depth, journals log identity, persists cursor and updates backend state from matching on-chain state.

## Gaps

- No production funding provider client, database migration plan, API authentication/authorization for any future mutating routes, queue/worker deployment or end-to-end operator workflow.
- Event listener does not detect a later canonical block-hash change or reverse a previously journaled transition after a reorg.
- No real PostgreSQL concurrency, process-kill/restart, persistent-volume, or multi-worker idempotency test.
- No HTTP rate limiting or load measurement for the quote API.

## Result

**Partial pass** for local orchestration primitives; not a deployed orchestration system.
