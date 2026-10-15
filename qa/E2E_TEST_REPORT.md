# End-to-end test report

## Result: BLOCKED / not run

No browser automation framework or E2E suite exists in the repository. The single frontend test renders SSR markup only; API tests invoke the ASGI application directly. The production deployment currently returns an empty eligible asset list, so an end-to-end quote journey cannot be completed without a configured, verified PoolKey.

## Journey status

| Journey | Status | Evidence / blocker |
|---|---|---|
| Dashboard opens and discloses estimate-only/no-spend behavior | Partial | SSR markup test passes; no browser session exercised |
| Discover asset and select USDC size | Blocked | Production asset list empty |
| Refresh v4 quote and Binance bid-depth estimate | Blocked | No configured pool; test sources mocked |
| Positive green / negative red P/L | Source only | Classes verified by inspection; no browser interaction test |
| WalletConnect/injected wallet | Not run | No browser provider / QR pairing test |
| Backend run creation, funding, v4 swap, simulated sale, settlement, claim | Out of current UI scope | Modules are disconnected and no provider/deployed testnet config exists |

No testnet or mainnet transactions were submitted. Do not interpret local mock integration as production E2E evidence.
