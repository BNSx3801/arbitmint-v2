// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {IHooks} from "v4-core/interfaces/IHooks.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/types/PoolId.sol";
import {BalanceDelta, BalanceDeltaLibrary} from "v4-core/types/BalanceDelta.sol";
import {BeforeSwapDelta} from "v4-core/types/BeforeSwapDelta.sol";

interface IArbitrageurHookContext {
    function hookRunContext()
        external
        view
        returns (bytes32 runId, bytes32 poolId, uint128 amountIn, bool active);
}

/// @notice Non-custodial v4 hook restricted to beforeSwap/afterSwap permissions.
/// @dev Deployment must mine a CREATE2 address whose low 14 bits are 0x00c0.
contract ArbitMintHook is IHooks, AccessControl {
    using PoolIdLibrary for PoolKey;
    using BalanceDeltaLibrary for BalanceDelta;

    uint160 public constant HOOK_PERMISSION_MASK = (1 << 14) - 1;
    uint160 public constant REQUIRED_HOOK_FLAGS = (1 << 7) | (1 << 6);

    error InvalidConfiguration();
    error UnauthorizedHookCallback();
    error UnauthorizedSwap();
    error PoolNotAllowed();
    error ExecutionDisabled();

    IPoolManager public immutable poolManager;
    IArbitrageurHookContext public immutable arbitrageur;
    mapping(bytes32 poolId => bool allowed) public allowedPools;
    bool public executionEnabled;

    struct SwapRecord {
        bytes32 poolId;
        address sender;
        int128 amount0;
        int128 amount1;
        uint64 timestamp;
        uint64 blockNumber;
    }

    mapping(bytes32 runId => SwapRecord) public swapRecords;

    event PoolPermissionUpdated(bytes32 indexed poolId, bool allowed);
    event ExecutionEnabledUpdated(bool enabled);
    event SwapObserved(
        bytes32 indexed runId,
        bytes32 indexed poolId,
        address indexed sender,
        int128 amount0,
        int128 amount1,
        uint64 timestamp,
        uint64 blockNumber
    );

    constructor(IPoolManager manager_, IArbitrageurHookContext arbitrageur_, address admin) {
        if (address(manager_) == address(0) || address(arbitrageur_) == address(0) || admin == address(0)) {
            revert InvalidConfiguration();
        }
        if ((uint160(address(this)) & HOOK_PERMISSION_MASK) != REQUIRED_HOOK_FLAGS) {
            revert InvalidConfiguration();
        }
        poolManager = manager_;
        arbitrageur = arbitrageur_;
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    function setExecutionEnabled(bool enabled) external {
        if (msg.sender != address(arbitrageur) && !hasRole(DEFAULT_ADMIN_ROLE, msg.sender)) {
            revert UnauthorizedHookCallback();
        }
        executionEnabled = enabled;
        emit ExecutionEnabledUpdated(enabled);
    }

    function setPoolAllowed(PoolId poolId, bool allowed) external {
        if (msg.sender != address(arbitrageur) && !hasRole(DEFAULT_ADMIN_ROLE, msg.sender)) {
            revert UnauthorizedHookCallback();
        }
        bytes32 id = PoolId.unwrap(poolId);
        allowedPools[id] = allowed;
        emit PoolPermissionUpdated(id, allowed);
    }

    function beforeSwap(
        address sender,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata params,
        bytes calldata hookData
    )
        external
        override
        returns (bytes4, BeforeSwapDelta, uint24)
    {
        _validateSwap(sender, key, params, hookData);
        return (IHooks.beforeSwap.selector, BeforeSwapDelta.wrap(0), 0);
    }

    function afterSwap(
        address sender,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata params,
        BalanceDelta delta,
        bytes calldata hookData
    ) external override returns (bytes4, int128) {
        (bytes32 runId, bytes32 poolId) = _validateSwap(sender, key, params, hookData);
        int128 amount0 = delta.amount0();
        int128 amount1 = delta.amount1();
        swapRecords[runId] = SwapRecord({
            poolId: poolId,
            sender: sender,
            amount0: amount0,
            amount1: amount1,
            timestamp: uint64(block.timestamp),
            blockNumber: uint64(block.number)
        });
        emit SwapObserved(runId, poolId, sender, amount0, amount1, uint64(block.timestamp), uint64(block.number));
        return (IHooks.afterSwap.selector, 0);
    }

    function _validateSwap(
        address sender,
        PoolKey calldata key,
        IPoolManager.SwapParams calldata params,
        bytes calldata hookData
    ) internal view returns (bytes32 runId, bytes32 poolId) {
        if (msg.sender != address(poolManager)) revert UnauthorizedHookCallback();
        if (!executionEnabled) revert ExecutionDisabled();
        if (sender != address(arbitrageur)) revert UnauthorizedSwap();
        poolId = PoolId.unwrap(key.toId());
        if (!allowedPools[poolId]) revert PoolNotAllowed();
        runId = abi.decode(hookData, (bytes32));
        (bytes32 activeRunId, bytes32 activePoolId, uint128 amountIn, bool active) =
            arbitrageur.hookRunContext();
        if (
            !active || runId != activeRunId || poolId != activePoolId || params.amountSpecified >= 0
                || uint256(-params.amountSpecified) != amountIn
        ) revert UnauthorizedSwap();
    }

    function beforeInitialize(address, PoolKey calldata, uint160) external pure override returns (bytes4) {
        revert UnauthorizedHookCallback();
    }

    function afterInitialize(address, PoolKey calldata, uint160, int24) external pure override returns (bytes4) {
        revert UnauthorizedHookCallback();
    }

    function beforeAddLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        bytes calldata
    )
        external
        pure
        override
        returns (bytes4)
    {
        revert UnauthorizedHookCallback();
    }

    function afterAddLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta,
        BalanceDelta,
        bytes calldata
    ) external pure override returns (bytes4, BalanceDelta) {
        revert UnauthorizedHookCallback();
    }

    function beforeRemoveLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        bytes calldata
    )
        external
        pure
        override
        returns (bytes4)
    {
        revert UnauthorizedHookCallback();
    }

    function afterRemoveLiquidity(
        address,
        PoolKey calldata,
        IPoolManager.ModifyLiquidityParams calldata,
        BalanceDelta,
        BalanceDelta,
        bytes calldata
    ) external pure override returns (bytes4, BalanceDelta) {
        revert UnauthorizedHookCallback();
    }

    function beforeDonate(address, PoolKey calldata, uint256, uint256, bytes calldata)
        external
        pure
        override
        returns (bytes4)
    {
        revert UnauthorizedHookCallback();
    }

    function afterDonate(address, PoolKey calldata, uint256, uint256, bytes calldata)
        external
        pure
        override
        returns (bytes4)
    {
        revert UnauthorizedHookCallback();
    }
}
