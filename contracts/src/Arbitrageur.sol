// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/interfaces/callback/IUnlockCallback.sol";
import {Currency} from "v4-core/types/Currency.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";
import {BalanceDeltaLibrary} from "v4-core/types/BalanceDelta.sol";
import {CurrencyLibrary} from "v4-core/types/Currency.sol";
import {PoolId, PoolIdLibrary} from "v4-core/types/PoolId.sol";
import {TickMath} from "v4-core/libraries/TickMath.sol";

interface IRunHook {
    function setExecutionEnabled(bool enabled) external;
    function setPoolAllowed(PoolId poolId, bool allowed) external;
    function poolManager() external view returns (address);
    function arbitrageur() external view returns (address);
}

/// @notice Testnet-only swap orchestration and backed claim accounting.
/// @dev Sandbox proceeds are operator-funded ERC20 transfers; they do not prove a real venue sale.
contract Arbitrageur is AccessControl, Pausable, ReentrancyGuard, IUnlockCallback {
    using SafeERC20 for IERC20;
    using PoolIdLibrary for PoolKey;
    using CurrencyLibrary for Currency;
    using BalanceDeltaLibrary for BalanceDelta;

    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    enum RunState {
        None,
        Created,
        Executing,
        Executed,
        Settling,
        Settled,
        Refunded
    }

    struct Run {
        address user;
        bytes32 poolId;
        uint128 principal;
        uint128 amountIn;
        uint128 amountOut;
        uint128 principalRecovered;
        uint128 shortfall;
        uint128 claimCredit;
        RunState state;
    }

    struct SwapRequest {
        bytes32 runId;
        PoolKey key;
        bool zeroForOne;
        uint128 amountIn;
        uint128 minAmountOut;
        uint256 deadline;
    }

    error InvalidAddress();
    error InvalidAmount();
    error InvalidState();
    error InvalidPool();
    error InvalidCurrency();
    error InvalidSwapDelta();
    error SlippageExceeded();
    error Expired();
    error UnauthorizedCallback();
    error UnsupportedTransferTax();
    error InsufficientBacking();

    IERC20 public immutable usdc;
    IPoolManager public immutable poolManager;
    IRunHook public hook;
    uint128 public immutable perRunCap;

    mapping(bytes32 runId => Run) public runs;
    mapping(address account => uint256 amount) public claimable;
    mapping(bytes32 poolId => bool allowed) public allowedPools;
    mapping(address token => bool allowed) public allowedTokens;

    uint256 public totalClaimable;
    bytes32 private _activeRunId;
    bytes32 private _activePoolId;
    uint128 private _activeAmountIn;

    event RunCreated(bytes32 indexed runId, address indexed user, uint256 principal, bytes32 poolId);
    event RunExecutionStarted(bytes32 indexed runId, uint256 amountIn, bytes32 poolId);
    event RunExecuted(bytes32 indexed runId, uint256 amountIn, uint256 amountOut, bytes32 poolId);
    event RunSettled(
        bytes32 indexed runId,
        uint256 proceeds,
        uint256 principalRecovered,
        uint256 shortfall,
        uint256 claimCredit
    );
    event RunRefunded(bytes32 indexed runId, address indexed user, uint256 amount);
    event Claimed(address indexed user, address indexed recipient, uint256 amount);
    event OperatorUpdated(address indexed oldOperator, address indexed newOperator);
    event PoolAllowed(bytes32 indexed poolId, bool allowed);
    event TokenAllowed(address indexed token, bool allowed);
    event HookUpdated(address indexed oldHook, address indexed newHook);

    constructor(IERC20 usdc_, IPoolManager poolManager_, address admin, address operator, uint128 perRunCap_)
    {
        if (
            address(usdc_) == address(0) || address(poolManager_) == address(0) || admin == address(0)
                || operator == address(0) || perRunCap_ == 0
                || perRunCap_ > uint128(type(int128).max)
        ) revert InvalidAddress();
        usdc = usdc_;
        poolManager = poolManager_;
        perRunCap = perRunCap_;
        _operator = operator;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(OPERATOR_ROLE, operator);
    }

    function setOperator(address newOperator) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (newOperator == address(0)) revert InvalidAddress();
        address oldOperator = _operator;
        if (oldOperator == newOperator) return;
        _grantRole(OPERATOR_ROLE, newOperator);
        _revokeRole(OPERATOR_ROLE, oldOperator);
        _operator = newOperator;
        emit OperatorUpdated(oldOperator, newOperator);
    }

    address private _operator;

    function setHook(IRunHook hook_) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (
            address(hook_) == address(0) || address(hook) != address(0)
                || hook_.poolManager() != address(poolManager) || hook_.arbitrageur() != address(this)
        ) revert InvalidAddress();
        hook = hook_;
        hook_.setExecutionEnabled(!paused());
        emit HookUpdated(address(0), address(hook_));
    }

    function setPoolAllowed(PoolKey calldata key, bool allowed) external onlyRole(DEFAULT_ADMIN_ROLE) {
        bytes32 poolId = PoolId.unwrap(key.toId());
        if (address(key.hooks) != address(hook)) revert InvalidPool();
        if (Currency.unwrap(key.currency0) == address(0) || Currency.unwrap(key.currency1) == address(0)) {
            revert InvalidCurrency();
        }
        allowedPools[poolId] = allowed;
        if (address(hook) != address(0)) hook.setPoolAllowed(key.toId(), allowed);
        emit PoolAllowed(poolId, allowed);
    }

    function setTokenAllowed(address token, bool allowed) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (token == address(0)) revert InvalidAddress();
        allowedTokens[token] = allowed;
        emit TokenAllowed(token, allowed);
    }

    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
        if (address(hook) != address(0)) hook.setExecutionEnabled(false);
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
        if (address(hook) != address(0)) hook.setExecutionEnabled(true);
    }

    function createRun(bytes32 runId, uint128 principal, PoolKey calldata key)
        external
        whenNotPaused
        nonReentrant
    {
        if (runId == bytes32(0) || principal == 0 || principal > perRunCap) revert InvalidAmount();
        bytes32 poolId = PoolId.unwrap(key.toId());
        if (!allowedPools[poolId]) revert InvalidPool();
        address token0 = Currency.unwrap(key.currency0);
        address token1 = Currency.unwrap(key.currency1);
        if (
            !allowedTokens[token0] || !allowedTokens[token1]
                || (token0 != address(usdc) && token1 != address(usdc))
        ) revert InvalidCurrency();
        if (runs[runId].state != RunState.None) revert InvalidState();

        runs[runId] = Run({
            user: msg.sender,
            poolId: poolId,
            principal: principal,
            amountIn: 0,
            amountOut: 0,
            principalRecovered: 0,
            shortfall: 0,
            claimCredit: 0,
            state: RunState.Created
        });
        uint256 beforeBalance = usdc.balanceOf(address(this));
        usdc.safeTransferFrom(msg.sender, address(this), principal);
        if (usdc.balanceOf(address(this)) - beforeBalance != principal) revert UnsupportedTransferTax();
        emit RunCreated(runId, msg.sender, principal, poolId);
    }

    function executeArbitrage(
        bytes32 runId,
        PoolKey calldata key,
        bool zeroForOne,
        uint128 amountIn,
        uint128 minAmountOut,
        uint256 deadline
    ) external onlyRole(OPERATOR_ROLE) whenNotPaused nonReentrant returns (uint256 amountOut) {
        Run storage run = runs[runId];
        bytes32 poolId = PoolId.unwrap(key.toId());
        if (
            run.state != RunState.Created || run.poolId != poolId || !allowedPools[poolId]
                || address(key.hooks) != address(hook)
        ) {
            revert InvalidState();
        }
        if (block.timestamp > deadline) revert Expired();
        if (amountIn == 0 || amountIn > run.principal || amountIn > perRunCap || minAmountOut == 0) {
            revert InvalidAmount();
        }
        address input = Currency.unwrap(zeroForOne ? key.currency0 : key.currency1);
        address output = Currency.unwrap(zeroForOne ? key.currency1 : key.currency0);
        if (!allowedTokens[input] || !allowedTokens[output] || input != address(usdc)) {
            revert InvalidCurrency();
        }
        if (address(hook) == address(0)) revert InvalidAddress();

        _activeRunId = runId;
        _activePoolId = poolId;
        _activeAmountIn = amountIn;
        run.state = RunState.Executing;
        emit RunExecutionStarted(runId, amountIn, poolId);
        SwapRequest memory request = SwapRequest({
            runId: runId,
            key: key,
            zeroForOne: zeroForOne,
            amountIn: amountIn,
            minAmountOut: minAmountOut,
            deadline: deadline
        });
        bytes memory result = poolManager.unlock(abi.encode(request));
        amountOut = abi.decode(result, (uint256));
        delete _activeRunId;
        delete _activePoolId;
        delete _activeAmountIn;

        if (amountOut < minAmountOut || amountOut > type(uint128).max) revert SlippageExceeded();
        uint128 unusedPrincipal = run.principal - amountIn;
        run.amountIn = amountIn;
        run.principalRecovered = unusedPrincipal;
        run.amountOut = uint128(amountOut);
        run.state = RunState.Executed;
        if (unusedPrincipal != 0) usdc.safeTransfer(run.user, unusedPrincipal);
        emit RunExecuted(runId, amountIn, amountOut, poolId);
    }

    function unlockCallback(bytes calldata data) external override returns (bytes memory) {
        if (msg.sender != address(poolManager) || _activeRunId == bytes32(0)) revert UnauthorizedCallback();
        SwapRequest memory request = abi.decode(data, (SwapRequest));
        if (
            request.runId != _activeRunId || PoolId.unwrap(request.key.toId()) != _activePoolId
                || request.amountIn != _activeAmountIn || block.timestamp > request.deadline
        ) revert UnauthorizedCallback();

        Currency inputCurrency = request.zeroForOne ? request.key.currency0 : request.key.currency1;
        Currency outputCurrency = request.zeroForOne ? request.key.currency1 : request.key.currency0;
        if (inputCurrency.isAddressZero() || outputCurrency.isAddressZero()) revert InvalidCurrency();

        IPoolManager.SwapParams memory params = IPoolManager.SwapParams({
            zeroForOne: request.zeroForOne,
            amountSpecified: -int256(uint256(request.amountIn)),
            sqrtPriceLimitX96: request.zeroForOne ? TickMath.MIN_SQRT_PRICE + 1 : TickMath.MAX_SQRT_PRICE - 1
        });
        BalanceDelta delta = poolManager.swap(request.key, params, abi.encode(request.runId));
        int128 amount0 = delta.amount0();
        int128 amount1 = delta.amount1();
        int128 inputDelta = request.zeroForOne ? amount0 : amount1;
        int128 outputDelta = request.zeroForOne ? amount1 : amount0;
        if (inputDelta >= 0 || outputDelta <= 0 || uint256(uint128(outputDelta)) < request.minAmountOut) {
            revert InvalidSwapDelta();
        }

        uint256 inputOwed = uint256(uint128(-inputDelta));
        uint256 outputReceived = uint256(uint128(outputDelta));
        if (inputOwed != request.amountIn) revert InvalidSwapDelta();
        poolManager.sync(inputCurrency);
        IERC20(Currency.unwrap(inputCurrency)).safeTransfer(address(poolManager), inputOwed);
        poolManager.settle();
        poolManager.take(outputCurrency, address(this), outputReceived);
        return abi.encode(outputReceived);
    }

    /// @notice Record returned principal and credit only proceeds actually transferred in this call.
    /// @dev `proceeds` is an operator-reported simulated venue result; token transfer proves funding only.
    function settleRun(bytes32 runId, uint128 proceeds) external onlyRole(OPERATOR_ROLE) nonReentrant {
        Run storage run = runs[runId];
        if (run.state != RunState.Executed || proceeds == 0) revert InvalidState();
        run.state = RunState.Settling;
        uint256 beforeBalance = usdc.balanceOf(address(this));
        usdc.safeTransferFrom(msg.sender, address(this), proceeds);
        if (usdc.balanceOf(address(this)) - beforeBalance != proceeds) revert UnsupportedTransferTax();

        uint128 recoveredFromProceeds = proceeds < run.amountIn ? proceeds : run.amountIn;
        uint128 principalRecovered = run.principal - run.amountIn + recoveredFromProceeds;
        uint128 shortfall = run.amountIn - recoveredFromProceeds;
        uint128 credit = proceeds > run.amountIn ? proceeds - run.amountIn : 0;
        uint256 nextTotalClaimable = totalClaimable + credit;
        if (usdc.balanceOf(address(this)) < nextTotalClaimable + recoveredFromProceeds) {
            revert InsufficientBacking();
        }

        run.principalRecovered = principalRecovered;
        run.shortfall = shortfall;
        run.claimCredit = credit;
        run.state = RunState.Settled;
        totalClaimable = nextTotalClaimable;
        claimable[run.user] += credit;
        if (recoveredFromProceeds != 0) usdc.safeTransfer(run.user, recoveredFromProceeds);
        if (usdc.balanceOf(address(this)) < totalClaimable) revert InsufficientBacking();
        emit RunSettled(runId, proceeds, principalRecovered, shortfall, credit);
    }

    function refundUnused(bytes32 runId) external onlyRole(OPERATOR_ROLE) nonReentrant {
        Run storage run = runs[runId];
        if (run.state != RunState.Created) revert InvalidState();
        run.state = RunState.Refunded;
        uint128 amount = run.principal;
        run.principalRecovered = amount;
        usdc.safeTransfer(run.user, amount);
        emit RunRefunded(runId, run.user, amount);
    }

    function claim(address recipient) external nonReentrant {
        if (recipient == address(0)) revert InvalidAddress();
        uint256 amount = claimable[msg.sender];
        if (amount == 0) revert InvalidAmount();
        claimable[msg.sender] = 0;
        totalClaimable -= amount;
        usdc.safeTransfer(recipient, amount);
        if (usdc.balanceOf(address(this)) < totalClaimable) revert InsufficientBacking();
        emit Claimed(msg.sender, recipient, amount);
    }

    function hookRunContext() external view returns (bytes32 runId, bytes32 poolId, uint128 amountIn, bool active) {
        return (_activeRunId, _activePoolId, _activeAmountIn, _activeRunId != bytes32(0));
    }
}
