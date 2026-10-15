# Contract security report

## Scope

Reviewed `Arbitrageur.sol`, `ArbitMintHook.sol`, and the local Foundry suite. No external audit or deployed contract review was performed.

## Controls present

- AccessControl separates default admin and operator; swap execution, settlement and refund require operator role.
- Pausable, ReentrancyGuard, per-run principal cap, token/pool allowlists, unique run IDs and state-gated operations.
- SafeERC20 for supported token transfers. Input/output deltas and minimum output are checked in the PoolManager callback.
- `totalClaimable` is increased only with proceeds transferred into the contract and checks balance backing before and after user principal recovery/claim.
- Settlement records recovered principal, shortfall and claim credit separately. This audit changed `settleRun` to accept zero proceeds, so a total loss can be finalized and the spent principal shortfall recorded.

## Local evidence

- Foundry suite: **7 passed, 0 failed, 0 skipped**.
- Local `TestPoolManager` double invokes the contract's actual `unlockCallback`, swap-delta handling, input settlement and output take. Tests cover positive credit backed by contract USDC, claim decrement, zero-proceeds full shortfall, operator access, duplicate run ID, refund and empty claim.
- Coverage output: Arbitrageur **83.95% lines / 83.46% statements / 30.91% branches / 71.43% functions**; Hook **0%**. Overall source line coverage **67.92%**. Foundry reported numerous source-anchor warnings, so branch numbers are indicative.
- `forge lint` reports multiple warnings (modifier ordering, casts, external-call/event ordering, strict transfer delta comparisons, etc.). No automatic suppression was added; each warning needs review before production deployment.

## Critical limits

- Mock manager is not the Uniswap v4 implementation. No fork test against the real PoolManager, real pool liquidity, actual hook call ordering, hookData propagation, or fee-on-transfer/reentrancy token matrix.
- Hook constructor requires CREATE2 low bits `0x00c0`, but no miner/deployer or permission-bit test exists. Hook source has zero executed coverage.
- No fuzz/property invariant tests for `contract USDC balance >= totalClaimable`, multiple users, repeated settlement/claim, or arbitrary deltas.
- No deployment manifest, verified addresses, bytecode verification or operational key model is present.
- Proceeds are explicitly operator-funded/simulated. Contract transfer evidence does not verify an external venue sale.

## Result

**NO-GO for testnet fund-flow release** until the real v4 path and Hook deployment/permissions have local fork/integration evidence and the critical invariants receive fuzz/property coverage and independent review.
