# Frontend test report

## Coverage and result

- `pnpm test` on Vitest 4.1.11: **1 test passed** (`DemoDashboard.test.tsx` SSR disclosure/unavailable state).
- `pnpm lint`: passed.
- `pnpm typecheck`: passed after QA changes.
- `pnpm build`: passed after dependency update.
- `pnpm audit`: after updating Vitest and PostCSS, 1 high advisory remains in transitive lint-only `braces@3.0.3`; upstream lists no patched version.

## Verified behavior

- Initial SSR markup labels the product read-only, shows quote unavailable, and includes WalletConnect QR affordance.
- Dashboard source calls backend asset and quote endpoints; 2.5-second interval stops on component cleanup and prevents overlapping quote fetches.
- UI uses bigint for display calculations and labels P/L as estimate; positive and negative values receive green/red classes.
- Wallet connection displays address and network only. Quote calls do not depend on wallet status.

## Not verified / gaps

- No DOM/browser test environment, Playwright or Cypress, or end-to-end suite.
- WalletConnect QR flow, injected-wallet account/network changes, disconnect, no-wallet browsing, and mobile deep links were not exercised in a browser.
- No configured eligible pool means the production UI currently cannot render a live asset/P&L result.
- Binance response time is shown as “Book received”; it is not a source event timestamp or proof the upstream book itself is fresh.
- One existing SSR test does not cover user interactions, interval timing, accessibility in a browser, or failure recovery.

## Result

**Partial pass** for static UI disclosure and build checks; end-to-end quote and wallet behavior remain unverified.
