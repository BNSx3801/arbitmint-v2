# AGENTS.md — ArbitMint

Testnet-only arbitrage orchestration MVP. It combines a real Uniswap v4 swap, a simulated external venue, and sandbox funding. Never represent estimates, simulator results, or operator assertions as verified real trading profit.

Read [`docs/PRD.md`](docs/PRD.md) for full requirements. This file contains non-obvious constraints and project commands.

## Stack and layout

- `contracts/`: Solidity (Foundry), OpenZeppelin, Uniswap v4. Arbitrageur and hook.
- `backend/`: Python 3.12+, FastAPI, web3.py, SQLAlchemy, PostgreSQL.
- `frontend/`: Next.js (App Router), TypeScript, wagmi, and viem.
- Store monetary amounts in integer base units. Never use floating-point arithmetic for money or claims.
- Store timestamps in UTC.

## Commands

Run from the repository root unless noted. Run the relevant block for the files changed. Run all three blocks before claiming a milestone is done. Install pinned Solidity dependencies as shown in the README, backend dependencies with `uv sync`, and frontend dependencies with `pnpm install` before running checks.

```sh
cd contracts && forge build && forge test -vvv && forge coverage
cd backend && uv sync && uv run pytest -q && uv run ruff check . && uv run mypy .
cd frontend && pnpm install && pnpm typecheck && pnpm lint && pnpm test
```

## Hard rules

- Default to paper, sandbox, and testnet operation. Do not use mainnet, real funds, or a real centralized exchange.
- Persist `CREATED` and each subsequent state before any external side effect. Require idempotency keys for every mutating operation.
- Maintain the contract invariant `USDC balance >= totalClaimable` after every credit. Claims must reduce both the user's claimable balance and `totalClaimable`.
- The hook must not custody funds or reenter Arbitrageur. Test the actual caller identity (router versus direct call); do not assume it.
- Label simulator results as simulated everywhere. Store the complete simulator configuration and inputs with every run.
- Never log secrets, private keys, or authorization headers.
- Fail closed on a stale oracle, missing liquidity, or mismatched hook permissions.
- Validate state transitions in both backend and contract where applicable. Record actor, reason, evidence, and before/after state.

## Accounting and terminology

- Estimated net profit, simulated proceeds, credited profit, and principal returned are distinct values; do not conflate them.
- Track shortfalls explicitly. Do not mark principal fully returned unless it was actually returned or covered.
- Reconciliation must detect and report differences. It must never silently auto-correct accounting.

## Definition of done

For each feature, relevant tests pass and types/lint are clean; state-machine and accounting invariants still hold; UI, API, and logs correctly label testnet, sandbox, and simulated behavior; and the change matches the corresponding functional requirement in the PRD.

## Do not

- Hardcode unverified addresses.
- Implement real venue execution, flash loans, multi-chain support, or EigenLayer in the MVP.
- Proceed past an unresolved gate that affects fund flow or contract security.
