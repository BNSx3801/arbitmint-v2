# ArbitMint

ArbitMint is a no-trade cross-venue market estimator. Users select an eligible asset paired with USDC, enter a hypothetical buy size, and see an estimated outcome based on a read-only Uniswap v4 exact-input quote on Unichain Mainnet and Binance public Spot bid depth. It never submits a trade, requests token approvals, signs a transaction, or spends tokens. The optional wallet connection only displays address and Unichain Sepolia network context.

The repository also contains an experimental Solidity contract slice and backend orchestration modules for a separate testnet workflow. They are not connected to this read-only quote path. Quote outputs are estimates, not fills or verified trading profit; Binance fees are configurable assumptions, and gas, transfers, bridging, withdrawals, and execution risk are excluded. The public Unichain RPC is rate-limited and intended for this MVP only.

The optional wallet context is Unichain Sepolia (chain ID 1301). Quote requests are independent of that wallet and call Unichain Mainnet read-only (chain ID 130). Eligible assets require a full, independently verified v4 PoolKey configuration and an active Binance USDC spot pair. No pool keys are bundled; until they are configured, the eligible asset list is empty and quotes report unavailable.

## Scope and safety

- Testnet only; no mainnet deployment or real user funds.
- Paper simulation only in the current frontend; no wallet funds or sandbox funds are used.
- DEX and CEX reference prices are simulated locally, and venue execution is hypothetical. They are not live quotes or exchange fills.
- Optional injected wallet and WalletConnect support are for testnet address/network context only. No signatures, approvals, or transactions are requested.
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

Required tools: Foundry (`forge`), uv, Node.js, and pnpm. Install them using their official installation instructions. Workspace manifests and lockfiles are checked in. Install project dependencies before running checks.

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

Run the read-only API with `cd backend && uv sync && uv run uvicorn arbitmint.app:app --reload`. Configure verified pools in `backend/.env` as documented in `backend/.env.example`; do not add unverified addresses or keys. Run the frontend with `cd frontend && pnpm install && pnpm dev`; open `http://localhost:3000`. Browser wallets are discovered through EIP-6963 with a legacy injected-provider fallback. WalletConnect QR requires a free public project ID in `frontend/.env.local` as `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID`. This identifier is not a wallet secret. The quote UI requires the backend to be running at `NEXT_PUBLIC_MARKET_API_URL` (defaults to `http://127.0.0.1:8000`); wallet connection is unrelated to API fetch failures. See [`docs/DEMO.md`](docs/DEMO.md) for behavior and boundaries. Never put credentials or private keys in source control; local `.env` files are ignored.
