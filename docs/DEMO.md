# ArbitMint Paper Simulator

Run the dashboard locally with `cd frontend && pnpm install && pnpm dev`, then open `http://localhost:3000`.

The dashboard loads eligible assets from the backend, enters a hypothetical USDC size, and observes an estimated P/L from a read-only Uniswap v4 quote on Unichain Mainnet and Binance Spot order-book bid depth. It refreshes every 2.5 seconds. Recording an estimate snapshot is local display state only. It does not request funds, submit a swap, or perform a venue sale.

## Wallet connection

Wallet connection is optional and only displays the connected address and network. Browser wallets are discovered through EIP-6963 with a legacy injected-provider fallback; WalletConnect QR is enabled when `NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID` is configured. A free public project ID is required for WalletConnect. The wallet context is Unichain Sepolia (chain ID 1301); market quotes independently use Unichain Mainnet read-only RPC. The UI does not read token balances, request signatures, ask for token approvals, or send transactions. Quotes work without connecting a wallet.

## Persistent labels

- **Live read-only market estimate** combines a Uniswap v4 quote from Unichain Mainnet with a Binance public order book. Binance fee is an assumption; gas, transfer, withdrawal, bridge, and execution costs are excluded.
- Eligible assets are the intersection of active Binance USDC Spot pairs and configured, verified Uniswap v4 pool keys. No default pool keys ship with the project; configure `UNISWAP_V4_POOLS_JSON` as described in `backend/.env.example`.
- A failed or stale source makes the estimate unavailable; the UI never substitutes generated prices.
- “Market API unreachable” means the FastAPI service is not running or its URL/CORS configuration is incorrect; it is unrelated to wallet connection.
- **Testnet · Unichain Sepolia** identifies the optional wallet context only.
- **Paper mode · no token spend** means the page cannot submit swaps or spend user assets.
- **Simulated market** identifies locally generated DEX/CEX reference prices; these are not live quotes.
- **Estimate** marks the momentary P/L model. It refreshes with the simulated prices and is not a promise or executable opportunity.
- **Simulate this trade** captures a local snapshot; it is not a real venue result or persisted backend run.

The P/L arithmetic uses integer base units. The current illustrative model deducts a fixed venue fee and estimated network cost; it does not model liquidity, slippage, exchange limits, withdrawal costs, or real-time execution risk. All market prices and resulting values are examples, not current quotes, wallet balances, or claims.
