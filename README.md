# ArbitMint

ArbitMint is a testnet-only arbitrage orchestration MVP. Its intended workflow combines an on-chain Uniswap v4 swap, sandbox funding, and a simulated external venue. The venue simulation is not a real exchange trade, and its proceeds are not verified real-world trading profit. Estimates are not guarantees.

The repository includes an initial Solidity contract slice for accounting, access control, direct v4 swaps, and a restricted hook. The backend now contains a persistent run state machine, sandbox funding adapter interface, deterministic venue simulator, confirmed event listener, and settlement coordinator. These orchestration modules are not yet wired into an HTTP API or verified as an end-to-end workflow. No deployment has been verified.

The selected target is Unichain Sepolia and the swap path is a direct PoolManager unlock/callback. PoolManager, token, pool, oracle, and sandbox-funding addresses and compatibility still require deployment verification before use.

## Scope and safety

- Testnet only; no mainnet deployment or real user funds.
- Sandbox funding only; sandbox funds have no real value.
- External venue execution is simulated. Simulator outcomes must be identified as simulated.
- No real centralized-exchange execution, flash loans, multi-chain routing, or EigenLayer integration in the MVP.
- Do not treat operator-reported or simulated values as independently verified external trading activity.

See [`docs/PRD.md`](docs/PRD.md) for requirements, acceptance criteria, trust assumptions, and implementation gates. Project-specific engineering constraints are in [`AGENTS.md`](AGENTS.md).

## Repository layout

```text
backend/     Python API and orchestration (uv)
contracts/   Solidity contracts and tests (Foundry)
deployment/  Deployment manifests and configuration
docs/        Product requirements and design notes
frontend/    Next.js application (pnpm)
scripts/     Development and operational scripts
```

## Tooling

Required tools: Foundry (`forge`), uv, Node.js, and pnpm. Install them using their official installation instructions. The package manifests and config files define the initial workspace. The pinned Solidity dependencies are installed in this checkout; backend/frontend dependencies and lockfiles are not yet installed or generated.

Install the pinned Solidity dependencies from the `contracts/` directory:

```sh
cd contracts
forge install --no-git OpenZeppelin/openzeppelin-contracts@v5.4.0 Uniswap/v4-core@v4.0.0
```

From the repository root, after installing the tools:

```sh
cd contracts && forge build && forge test -vvv && forge coverage
cd backend && uv sync && uv run pytest -q && uv run ruff check . && uv run mypy .
cd frontend && pnpm install && pnpm typecheck && pnpm lint && pnpm test
```

The funding adapter is provider-neutral and refuses to operate unless an explicitly injected sandbox provider declares its lifecycle verified. The PRD's Circle workflow gate is still unresolved, so there is no enabled Circle client. Settlement requires an operator transaction and preapproved testnet USDC; this is not automated by a verified funding/redemption integration. Never put credentials in source control; local `.env` files are ignored. Use `.env.example` only for names and non-secret placeholders.
