# ARBITMINT

## PRODUCT REQUIREMENTS DOCUMENT

**Final revised version • v1.0**  
**Testnet-only MVP | October 14, 2026**

**Owner:** Bal Narayan Singh  
**Status:** Implementation baseline for review

**Core principle:** distinguish on-chain facts, operator actions, estimates, and simulated outcomes.

---

## Document control

**Version:** 1.0 | **Status:** Implementation baseline for review | **Date:** October 14, 2026  
**Owner:** Bal Narayan Singh

**Purpose:** Define a reproducible, testnet-only ArbitMint MVP. This document supersedes Draft v0.1 when approved. It distinguishes implemented behavior from planned behavior and does not claim live arbitrage profitability.

---

## 1. Executive summary

ArbitMint is a testnet-only arbitrage orchestration prototype. A user selects a supported asset and Uniswap v4 pool. The system evaluates a candidate trade using pool quotes, a reference-price sanity check, and an explicit cost model. If the opportunity passes configured thresholds, the backend provisions sandbox USDC, initiates a real on-chain v4 swap, and passes the acquired token to a simulated external venue. The simulator returns a recorded hypothetical execution result. The backend then initiates settlement, the contract accounts for returned principal and verified USDC available for claims, and the user may claim credited USDC on-chain.

The MVP demonstrates reliable orchestration, real testnet contract integration, transparent simulation, and auditable accounting. It does not demonstrate real exchange execution, risk-free arbitrage, guaranteed profits, production-grade custody, or a production-ready funding service.

**Core product principle:** never represent an estimate, operator assertion, or simulated venue result as independently verified real-world trading profit.

---

## 2. Problem, users, and value proposition

### Problem

Cross-venue arbitrage requires opportunity detection, trade-size and cost analysis, capital provisioning, on-chain execution, an external sale, and reconciliation across systems. These steps create operational and engineering complexity.

### Proposed solution

ArbitMint packages the workflow into a single run with a persistent state machine, an on-chain execution and claim path, an explicit simulated venue, and an audit trail.

### Primary users

- **DeFi-curious trader:** wants to inspect an opportunity and follow a run without operating a trading bot.
- **Technical reviewer:** wants reproducible evidence of smart-contract, integration, backend, and testing competence.
- **Operator/builder:** monitors runs, investigates failures, and performs only the documented recovery actions.

### Value proposition

- A transparent go/no-go decision with a visible cost breakdown.
- A traceable run from funding through execution, simulation, settlement, and claim.
- Explicit separation of on-chain facts, off-chain operator actions, and simulated outcomes.

---

## 3. Goals, non-goals, and success metrics

### Goals

- **G1.** Complete one reproducible end-to-end testnet run: sandbox funding, confirmed v4 swap, simulated venue sale, settlement, and user claim.
- **G2.** Replace all placeholders in the execution path with working, tested code.
- **G3.** Enforce access control, run-state transitions, claim backing, and per-run limits.
- **G4.** Make the README and UI accurately label testnet, sandbox funding, and simulated venue behavior.
- **G5.** Deliver reproducible setup instructions, automated tests, a demo recording, and an architecture/trust note.

### Non-goals

- Mainnet deployment or use of real user funds.
- Real centralized-exchange execution, production custody, or rebalancing.
- Flash-loan arbitrage, multi-chain routing, EigenLayer integration, or production compliance/KYC.
- Any guarantee of profit or claim that the MVP proves a profitable trading strategy.

### Success metrics

| Metric | Target / acceptance criterion |
|--------|-------------------------------|
| End-to-end reliability | 10 consecutive scripted testnet runs complete; failed-path tests are reported separately and must reach a defined terminal or recoverable state. |
| Accounting reconciliation | At every checkpoint, total outstanding claims are no greater than contract USDC balance; no unexplained ledger difference after 10 runs. |
| Contract tests | At least 90% line coverage, plus fuzz/invariant tests and at least one v4 integration/fork test. Coverage is not treated as proof of correctness. |
| Opportunity check latency | Go/no-go response in under 5 seconds under documented local/testnet conditions; report p95 and test setup. |
| Reproducibility | A reviewer can clone, install, configure, and reproduce the demo in under 30 minutes using the README, excluding third-party service outages. |
| Simulation disclosure | Every screen and exported run record identifies simulated venue results and sandbox/testnet context. |
| Recovery | Duplicate requests/events and a backend restart do not cause duplicate swaps, sales, settlements, or profit credits. |

---

## 4. Scope and terminology

### MVP scope

- One selected testnet, one supported USDC token, a bounded set of approved tokens and v4 pools, one hook configuration, one simulated venue, and one operator-controlled backend.
- Exact-input v4 swaps with minimum-output enforcement and per-run limits.
- Circle sandbox integration only after the specific supported workflow, chain, token, and recipient semantics have been verified in an integration spike.
- A simulated venue with deterministic/reproducible settings for spread, depth, fee, latency, and failure behavior.
- Persistent run records, structured logs, reconciliation export, and a user claim flow.

### Terminology

- **Estimated net profit:** pre-trade model output; not a promise and not a realized result.
- **Simulated proceeds:** proceeds calculated by the configured simulator; not real exchange proceeds.
- **Credited profit:** amount recorded as claimable by the contract after settlement checks; not proof of a real external trade.
- **Principal:** amount allocated to a run. The specification must distinguish principal returned, principal recovered, and any shortfall.
- **Run ID:** unique identifier used across API requests, database records, events, and contract state.

### Deployment selection gate

The target network is an explicit go/no-go decision before implementation. Select Sepolia or Unichain Sepolia only after verifying the required Uniswap v4 PoolManager/router/periphery deployments, supported token addresses, usable pool liquidity, oracle availability, and Circle sandbox compatibility. Record chain ID, addresses, deployment versions, and verification date in a checked-in deployment manifest. Do not hardcode unverified addresses.

---

## 5. End-to-end workflow and run state machine

### Happy path

1. User selects an approved asset/pool and requests an opportunity check.
2. Opportunity engine fetches a v4 exact-input quote, reference price, venue simulation quote, costs, and candidate-size results.
3. If the opportunity meets configured thresholds, the user confirms. The backend creates a unique run ID and persists CREATED before external side effects.
4. Funding adapter requests sandbox USDC and polls/records the provider status. Execution is prohibited until the funding evidence and required on-chain balance are confirmed.
5. Operator submits executeArbitrage for the run. The backend persists transaction intent/hash before waiting for confirmation; the contract enforces run limits and state.
6. After required confirmations, the backend verifies the transaction receipt and event, token output, and contract state, then marks EXECUTED.
7. The simulated venue adapter computes and records a sale result from the actual acquired token amount, configured depth/spread/fee/latency, and the captured simulation inputs. Mark SOLD only after a durable result exists.
8. The settlement caller transfers proceeds to the contract and requests settlement. Contract checks and accounting must ensure credits are backed by actual USDC held, not only by the proceeds argument.
9. The backend verifies settlement and principal accounting, then attempts sandbox redemption only according to the verified provider workflow. Mark REDEEMED only after confirmed provider status.
10. User claims any contract-recorded claimable amount. UI verifies the resulting on-chain state.

### State definitions

| State | Entry condition | Recovery / permitted next state |
|-------|-----------------|---------------------------------|
| CREATED | Run and immutable inputs persisted; no funding/execution assumed. | FUNDED or FAILED |
| FUNDED | Funding provider status confirmed and required on-chain USDC balance verified. | EXECUTED or FAILED |
| EXECUTED | Swap transaction confirmed; expected event/output and run state verified. | SOLD, STUCK, or LOSS |
| SOLD | Simulated venue result durably recorded with inputs, fees, proceeds, and timestamp. | SETTLED, STUCK, or LOSS |
| SETTLED | Contract settlement confirmed; principal disposition and claim credit reconciled. | REDEEMED or terminal settlement status |
| REDEEMED | Sandbox redemption confirmed, if applicable to the chosen provider flow. | Terminal |
| FAILED | Failure occurred before an irreversible leg or safe continuation is impossible. | Terminal or operator-reviewed recovery; never silently reset |
| STUCK | Progress is uncertain or requires operator action; asset/fund location is recorded. | Retry/reconcile or LOSS/SETTLED as allowed by explicit policy |
| LOSS | Run outcome is loss-making and shortfall policy has been applied or explicitly remains outstanding. | Terminal only after principal disposition is recorded |

All state transitions must be validated by the backend and, where relevant, by the contract. Persist transition history with timestamp, actor, reason code, transaction hash/provider reference, and before/after state. A state name alone is not evidence that an operation occurred.

### Failure handling

- **Funding fails:** no on-chain execution; record provider response and mark FAILED.
- **Swap reverts:** verify whether funds remain in the contract, then refund only under the permitted state and accounting rules.
- **Transaction submission times out:** reconcile transaction hash, nonce, receipt, and on-chain run state before any retry.
- **Simulated sale fails/times out:** persist the failure; retry idempotently under bounded backoff or mark STUCK for operator review.
- **Proceeds are below principal:** record recovered proceeds and shortfall separately. Do not credit profit. Do not mark principal fully returned unless the amount is actually returned or the shortfall is covered.
- **Settlement succeeds but backend loses response:** query chain state and events before retrying.
- **Redemption fails:** keep on-chain settlement facts intact; retry/reconcile the provider operation separately.

---

## 6. Functional requirements

### 6.1 Opportunity engine

- **FR-1.1 (P0):** Quote approved pools for bounded candidate trade sizes using exact-input v4 quoting.
- **FR-1.2 (P0):** Fetch a configured Chainlink feed where available; reject zero, negative, or stale answers using feed-specific decimals and heartbeat/staleness policy. If no suitable feed exists, fail closed or use a documented non-oracle demo mode that is clearly labelled.
- **FR-1.3 (P0):** Calculate estimated net profit using quoted purchase cost/output, simulated executable sale proceeds for the acquired quantity, pool fees/price impact, gas, venue fees/spread, applicable funding/redemption costs, and configurable safety buffer.
- **FR-1.4 (P0):** Evaluate bounded candidate sizes and select the maximum estimated net profit subject to maximum size, minimum output, depth, and loss limits. Return the quote timestamp and model assumptions.
- **FR-1.5 (P0):** Return GO/NO-GO and stable reason codes including STALE_ORACLE, NO_POOL_LIQUIDITY, DEPTH_TOO_LOW, BELOW_THRESHOLD, COSTS_EXCEED_SPREAD, SIZE_LIMIT, and QUOTE_FAILED.
- **FR-1.6 (P0):** Separate estimated profit from realized/simulated settlement outcome in API schema and UI.
- **FR-1.7 (P1):** Make minimum net profit, maximum size, maximum slippage, and safety buffer configurable through validated configuration.

#### Pricing and economics rule

For candidate size q:  
**estimated net profit = simulated executable sale proceeds(q) − on-chain purchase cost(q) − estimated gas − pool fees/price impact not already included in the quote − venue fees/spread not already included in simulated proceeds − applicable funding/redemption costs − safety buffer.**

Each cost must be included exactly once. The Chainlink feed is a reference/sanity check, not an executable venue and never the source of settlement amounts.

The simulator must quote/sell the actual acquired quantity and model finite depth, fees, spread, latency, and optional price movement/failure. Store all parameters with each run so results are reproducible. Never describe a simulator result as a live arbitrage profit.

### 6.2 Funding

- **FR-2.1 (P0):** Implement a Circle sandbox client only for a verified, documented provider workflow; secrets are injected via environment/secret store and never committed.
- **FR-2.2 (P0):** Persist provider request/reference ID, amount, currency, status, timestamps, and sanitized error details per run.
- **FR-2.3 (P0):** Do not execute until provider status and required on-chain USDC balance are independently confirmed.
- **FR-2.4 (P0):** Define principal return and redemption as separate steps. Verify whether the chosen sandbox workflow actually supports the proposed chain/token movement and redemption semantics before coding the complete flow.
- **FR-2.5 (P0):** Label all funds as sandbox/testnet in UI, logs, exports, and README; state that sandbox funds have no real value and production minting is not free capital.

### 6.3 Smart contracts — Arbitrageur

- **FR-3.1 (P0):** Implement a real exact-input v4 swap through the selected supported router or PoolManager unlock/callback flow, with minimum-output checks and correct delta settlement.
- **FR-3.2 (P0):** Restrict executeArbitrage and settle to the configured operator role. Owner may rotate operator and pause/unpause. Emit events for privileged configuration changes.
- **FR-3.3 (P0):** Maintain per-run on-chain state keyed by runId; prevent duplicate execution, settlement, refund, and profit credit.
- **FR-3.4 (P0):** Track totalClaimable and require actual contract USDC balance to cover all outstanding claims after any credit. Claims reduce both the user's claimable balance and totalClaimable.
- **FR-3.5 (P0):** Use SafeERC20 for supported token movements and reset approvals to zero after use where approval-based transfers are used.
- **FR-3.6 (P0):** Enforce per-run USDC cap, token/pool allowlists, and pause checks before external calls.
- **FR-3.7 (P0):** Emit events for every meaningful state transition and include runId and relevant amounts.
- **FR-3.8 (P0):** Implement explicit unused-funds refund rules and per-run principal disposition; refund paths must be idempotent and state-gated.
- **FR-3.9 (P0):** Define loss handling so a shortfall is not misrepresented as principal returned. Track principal recovered, shortfall, and any separately funded cover.

### 6.4 Hook

- **FR-3.10 (P0):** Implement beforeSwap restrictions for the authorized execution path, active run, allowed pool/token, and per-run maximum size.
- **FR-3.11 (P0):** Define exactly how runId is associated with the swap and which address is observed by the hook when routing through a router. Test caller identity rather than assuming the Arbitrageur is msg.sender.
- **FR-3.12 (P0):** Implement afterSwap recording of relevant deltas and pool state needed for audit/reconciliation; do not use a spot post-swap price as proof of external execution or realized profit.
- **FR-3.13 (P0):** Mine/deploy the hook address using CREATE2 or the repository's supported deployment tooling; assert the deployed address has the required permission bits and matches the compiled hook configuration.
- **FR-3.14 (P0):** Hook does not custody user funds and cannot reenter the Arbitrageur. Add tests for callback order, caller, data, pool key, and permission configuration.
- **FR-3.15 (P2):** Add liquidity callbacks only if a demonstrated product requirement uses their output.

Any allow-all/demo mode must be isolated to a test-only deployment/configuration and must not be enabled in the standard MVP deployment. The system must fail closed if required hook permissions or pool configuration do not match.

### 6.5 Backend

- **FR-4.1 (P0):** Persist run orchestration state and implement idempotent steps; support restart and reconciliation after uncertain outcomes.
- **FR-4.2 (P0):** Listen for relevant events, wait for configured confirmation depth, handle duplicate delivery, and reconcile event data against on-chain state.
- **FR-4.3 (P0):** Define VenueAdapter quote/sell interface. SimulatedVenue must return quantity, gross proceeds, fees, net proceeds, latency, simulation parameters, and deterministic run reference.
- **FR-4.4 (P0):** Settlement validates nonnegative amounts, plausible bounds against the recorded quote, and actual USDC received by the contract. Operator-provided values alone are not proof of funds.
- **FR-4.5 (P0):** Operator key comes from environment/secret store, is testnet-only, and has documented permissions and rotation procedures.
- **FR-4.6 (P0):** Provide POST /opportunities/check, POST /runs, GET /runs/{id}, and GET /runs with input validation, pagination, and consistent error schemas.
- **FR-4.7 (P0):** Persist transaction intent/hash before waiting for receipts; on timeout, reconcile before retrying. Use bounded exponential backoff and expose STUCK reason codes.
- **FR-4.8 (P0):** Store timestamps in UTC and use integer token base units for monetary/token amounts; avoid floating-point arithmetic for settlement/accounting.
- **FR-4.9 (P1):** Add operator alerts for STUCK runs and a documented manual recovery procedure.

### 6.6 Frontend

- **FR-5.1 (P0):** Wallet connect, approved asset/pool selection, and opportunity result with complete cost breakdown and quote freshness.
- **FR-5.2 (P0):** Run timeline with state, timestamps, reason codes, and transaction links where applicable.
- **FR-5.3 (P0):** Show estimated result separately from final simulated/settled result; provide claim action only when on-chain claimable balance is positive.
- **FR-5.4 (P0):** Persistently display Testnet, Sandbox funds, and Simulated venue labels.
- **FR-5.5 (P0):** Explain that opportunities can disappear, execution can lose value, and simulated profits are not real trading profits.
- **FR-5.6 (P0):** Render FAILED, STUCK, and LOSS states with a clear explanation; never show a success state based only on a backend response without the required confirmation.

### 6.7 Observability and reconciliation

- **FR-6.1 (P0):** Structured logs include runId, correlation ID, operation, state transition, provider reference, transaction hash, and sanitized error code.
- **FR-6.2 (P0):** CSV ledger export and reconciliation script compare contract balances, outstanding claims, per-run accounting, provider receipts, and backend records.
- **FR-6.3 (P0):** Reconciliation reports missing events, duplicate records, balance differences, unsettled principal, and unexplained amounts; it must not silently auto-correct accounting.
- **FR-6.4 (P0):** Never log private keys, secrets, authorization headers, or unnecessary personal data.

---

## 7. Data model and API contracts

### Core entities

| Entity | Required fields (minimum) |
|--------|---------------------------|
| Run | runId, user, chainId, pool key, token addresses, principal amount in base units, acquired quantity, proceeds, fees, estimated result, realized/simulated result, state, state history, transaction hashes, mint/provider reference, quote snapshot, simulator configuration, timestamps, failure/recovery metadata. |
| FundingRecord | runId, provider reference, request ID, amount, status, created/updated timestamps, sanitized response metadata. |
| OpportunityCheck | request ID, pool/token inputs, quote block/time, oracle answer/time/decimals, simulator quote, candidate sizes, cost breakdown, decision, reason code, model version. |
| LedgerEntry | entry ID, runId, type, amount in base units, token, source evidence, transaction/provider reference, timestamp, balance/checkpoint after entry. |
| TransactionRecord | chain ID, transaction hash, nonce where applicable, operation, submission time, receipt status, block number, confirmation status. |

### API requirements

- **POST /opportunities/check:** validate pool/token allowlist and size range; return quote freshness, candidate-size analysis, cost breakdown, estimated net profit, GO/NO-GO, and reason code.
- **POST /runs:** require a successful, sufficiently fresh opportunity check and explicit user confirmation; accept an idempotency key; persist CREATED before side effects.
- **GET /runs/{id}:** return current state, state history, estimated and realized/simulated values, transaction/provider evidence, and recovery status.
- **GET /runs:** return paginated runs scoped to the authorized user/operator context.

API schemas must use integer base units for amounts, explicit token decimals, UTC timestamps, stable enums, and versioned error responses. Do not accept arbitrary token or pool addresses from the frontend without server-side allowlist validation.

---

## 8. Architecture and trust model

### Components

- **Frontend:** Next.js dashboard and wallet integration.
- **Backend:** FastAPI modular application with opportunity engine, run orchestrator, funding adapter, chain adapter, venue adapter, and reconciliation jobs.
- **Persistence:** relational database for durable runs, transition history, idempotency keys, receipts, transaction tracking, and ledger entries.
- **On-chain:** Arbitrageur contract, ArbitMint hook, selected Uniswap v4 deployment, approved pool and tokens.
- **External dependencies:** Circle sandbox API and a configured Chainlink feed where supported.

### Trust assumptions and limits

- The backend/operator is trusted to run the simulator and report its output honestly. The contract cannot prove a real external sale occurred.
- Contract-held USDC and on-chain events can establish on-chain balances and state, but cannot independently establish the truth of off-chain simulation inputs.
- Circle sandbox funds have no real value; provider responses and on-chain balances must be reconciled separately.
- The Chainlink feed is a reference/sanity check only; it is not a tradable venue.
- The MVP is testnet-only and is not audited or approved for real funds.

A future real-venue implementation would need a separate custody/key-management design, venue API authentication, reconciliation and dispute handling, withdrawal/rebalancing policy, operational controls, and a fresh security/compliance review. It is not an adapter-only change.

---

## 9. Security, failure, and operational requirements

- Use established, pinned OpenZeppelin and Uniswap dependencies; record versions/commit hashes and verify clean builds.
- Apply checks-effects-interactions, reentrancy protection where appropriate, least-privilege roles, token/pool allowlists, per-run caps, and pause controls.
- Use SafeERC20 for token transfers and account for tokens with nonstandard return behavior. Prefer explicitly supported tokens rather than claiming arbitrary ERC-20 compatibility.
- Protect operator keys; use separate testnet keys, environment/secret-store injection, .gitignore, and automated secret scanning.
- Validate oracle answer, decimals, timestamp, staleness threshold, and feed suitability for the selected network/asset.
- Set minimum output and deadline/expiry controls appropriate to the chosen v4 execution path.
- Bound retries; distinguish retryable, terminal, and uncertain outcomes. Never retry an uncertain on-chain action without reconciliation.
- Record every manual operator action with actor, timestamp, reason, and resulting evidence.
- Run static analysis and dependency checks; document that automated tests do not constitute an independent security audit.

---

## 10. Testing and acceptance plan

### Contract tests

- Access control: non-operator cannot execute or settle; unauthorized callers cannot change operator/pause configuration.
- Run lifecycle: execute once, settle once, refund only in permitted states, no double credit, no invalid transition.
- Accounting invariants: contract USDC balance is at least totalClaimable; each claim reduces user claimable and totalClaimable consistently; no credit is created without adequate contract-held backing.
- Principal disposition: successful return, partial recovery, explicit shortfall, unused-funds refund, and failed swap paths.
- Token behavior: SafeERC20 transfer failures, nonstandard return behavior for supported test tokens, and approval reset.
- Hook behavior: permission bits, authorized caller/router semantics, run ID association, pool allowlist, maximum size, callback order, and swap deltas.

### Backend tests

- Provider pending/success/failure responses, timeouts, duplicate webhooks/poll results, and restart recovery.
- Transaction timeout after successful submission, duplicate event delivery, confirmation delay, reorg/receipt uncertainty where test environment permits, and idempotent retry.
- Simulator depth limits, fees, spread, latency, price movement, deterministic replay, and injected failures.
- Settlement result inconsistent with the quote, missing USDC transfer, duplicate settlement request, and reconciliation mismatch.

### End-to-end acceptance

1. Clean checkout builds and tests using documented commands.
2. A configured supported testnet deployment executes a real v4 swap with verified output.
3. Simulator inputs and outputs are stored and visible in the run record.
4. Settlement is backed by actual contract-held USDC; claimable never exceeds the contract's USDC balance.
5. User claim succeeds and the on-chain claimable amount decreases appropriately.
6. Ten consecutive scripted happy-path runs reconcile with no unexplained difference.
7. Failure-injection runs reach a correct recoverable or terminal state without double execution or credit.
8. A reviewer can reproduce the demo within 30 minutes under documented dependency/service assumptions.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Non-atomic on-chain/off-chain legs | Explicit STUCK/LOSS states, bounded retries, recorded asset location, recovery procedures, and clear disclosure that execution is not atomic. |
| Opportunity disappears before sale | Fresh quotes, conservative buffer, simulated latency/price movement, minimum-output limits, and no profit guarantee. |
| Unrealistic simulation | Expose simulator configuration, use finite depth and fees, store inputs/results, and label all proceeds simulated. |
| Operator custody/honesty | Testnet-only, per-run caps, limited permissions, audit trail, and explicit trust statement. |
| Unbacked claims/double accounting | totalClaimable invariant, per-run state, SafeERC20, fuzz/invariant tests, and reconciliation. |
| Hook address/permission errors | Deployment script mines/asserts permission bits and tests deployed configuration. |
| v4 integration complexity | Early feasibility spike, pinned dependencies, integration tests, and fork test where feasible. |
| Circle sandbox incompatibility | Validate exact provider workflow and chain/token mechanics before implementing the complete lifecycle; fail closed if unsupported. |
| Secrets leakage | Environment/secret store, .gitignore, pre-commit scanning, and log redaction. |
| Stale/unsuitable oracle | Feed-specific staleness and decimal checks; fail closed or use a clearly labelled demo mode. |
| Dependency drift | Pin package versions and commit hashes; record deployment addresses and versions. |
| Misleading public claims | Claims ledger, UI disclosures, and milestone-based README/resume wording. |

---

## 12. Milestones and claims ledger

| Milestone | Scope | Exit criteria | Permitted claim after completion |
|-----------|-------|---------------|----------------------------------|
| M0 — Repository baseline | Dependencies, clean build, README truthfulness, configuration template. | Clean clone builds; tests run; no secrets committed; scope and trust model documented. | Repository baseline and reproducible setup only. |
| M1 — On-chain core | Arbitrageur, hook, v4 swap, access control, accounting, refunds, deployment tooling. | Unit/fuzz/invariant tests pass; v4 integration test passes; hook permission bits verified; accounting invariant demonstrated. | Built a Solidity settlement contract and v4 hook tested on the named testnet. |
| M2 — Backend and simulation | Persistent orchestrator, funding adapter, simulator, event listener, settlement, reconciliation. | End-to-end scripted run completes; duplicate/restart tests pass; simulator records inputs and outputs. | Built an orchestration backend with a simulated external venue and documented sandbox funding. |
| M3 — Frontend and demo | Dashboard, run timeline, ledger, claim flow, reliability suite, recording. | Ten happy-path runs reconcile; failure cases are handled; reviewer reproduces demo from README. | Built an end-to-end testnet prototype with a simulated venue, public repository, and demo. |
| M4 — Optional research | Paper-trading venue, on-chain-only arbitrage variant, EigenLayer exploration. | Separate design and implementation evidence for each extension. | Claim only the specific extension that was actually implemented and tested. |

Do not claim “real CEX arbitrage,” “risk-free profit,” “flash-loan arbitrage,” “no upfront capital,” “production-ready,” or “EigenLayer-integrated” unless the exact claim is independently supported by implemented and tested behavior. A simulated venue must always be named as simulated.

---

## 13. Open decisions and implementation gates

| ID | Decision / gate | Required resolution |
|----|-----------------|---------------------|
| D1 | Target testnet | Choose only after verifying v4 deployment, pool liquidity, token addresses, oracle availability, and funding compatibility. Record chain ID and addresses. |
| D2 | Circle sandbox lifecycle | Document the exact API operations and prove the end-to-end funding, on-chain balance, principal return, and redemption semantics. |
| D3 | Backend language | Recommendation: Python, FastAPI, and web3.py to align with the stated owner preference; update README and lock dependencies. |
| D4 | Venue simulation model | Specify pricing source, depth model, spread, fee, latency, price movement, determinism, and output schema. |
| D5 | Swap routing and hook caller | Choose router vs direct PoolManager unlock flow and test the actual caller identity and runId propagation. |
| D6 | Loss/shortfall policy | Define whether shortfall is covered by a test funding reserve or remains explicitly outstanding; do not imply principal was returned otherwise. |
| D7 | Run persistence and idempotency | Select database and define uniqueness constraints/idempotency keys for every side effect. |
| D8 | Hook scope | P0: beforeSwap/afterSwap only; liquidity callbacks remain P2 unless justified. |
| D9 | EigenLayer and flash-loan work | Defer beyond MVP. |
| D10 | Original submission reconciliation | Locate the original hook/backend/Python code and compare it with this PRD before making claims about earlier functionality. |

Implementation must not proceed past the relevant gate while an unresolved decision would change fund flow, contract security, or core integration semantics.

---

## 14. Out of scope and future work

- Mainnet deployment and real funds, including a separate security and compliance review.
- Real exchange trading, custody, API keys, withdrawals, and venue rebalancing.
- Atomic flash-loan arbitrage between on-chain venues.
- EigenLayer-based computation or attestations.
- Multi-chain and multi-asset routing.
- Independent security audit and production operational readiness.

---

## 15. Definition of done

- The chosen network and all required addresses/versions are recorded and verified.
- The repository builds from a clean clone and the README matches the implementation.
- The v4 swap is real on the selected testnet and hook permissions/caller semantics are tested.
- The backend has durable state, idempotency, restart recovery, and reconciliation.
- The simulator is explicitly labelled, deterministic when configured, and records its assumptions.
- Contract accounting invariants and failure paths are covered by automated tests.
- Ten scripted happy-path runs complete and reconcile; fault-injection runs do not create duplicate execution or unbacked claims.
- UI, API, logs, and exported ledger distinguish estimates, simulated outcomes, on-chain facts, and operator-reported actions.
- A demo recording, architecture/trust note, test report, deployment manifest, and reproducible README are delivered.

---

## Appendix A — Required demo disclosures

- “Testnet prototype — no real user funds.”
- “Funding uses a sandbox workflow; sandbox funds have no real value.”
- “External venue execution is simulated. Proceeds and profit are simulation outputs, not real exchange trades.”
- “Estimated profitability is not guaranteed. Prices, fees, liquidity, and execution timing can change.”
- “The backend operator is trusted to report simulated venue results; the contract cannot independently verify an off-chain sale.”

---

## Appendix B — Reconciliation equations

All values are stored and computed in integer base units with explicit token decimals. Floating-point arithmetic must not be used for token settlement or claim accounting.

- Outstanding claim invariant: contract USDC balance ≥ totalClaimable.
- After a claim of amount x: userClaimableAfter = userClaimableBefore − x; totalClaimableAfter = totalClaimableBefore − x; contract USDC balance decreases by x, subject to successful token transfer.
- Per-run accounting must reconcile funded principal, swap output, simulated sale quantity, gross proceeds, fees, net proceeds, principal recovered/returned, shortfall/cover, credited claim, and any remaining assets.
- Estimated net profit = estimated executable sale proceeds − purchase cost − non-duplicated execution costs − safety buffer.

These equations do not establish that the external sale was real. In the MVP, sale proceeds remain simulated and must be identified as such.

---

*ArbitMint PRD v1.0 • Testnet-only MVP*  
*October 14, 2026*
