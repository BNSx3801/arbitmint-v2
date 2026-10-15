// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Arbitrageur, IRunHook} from "../src/Arbitrageur.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/interfaces/callback/IUnlockCallback.sol";
import {Currency} from "v4-core/types/Currency.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/types/PoolId.sol";
import {IHooks} from "v4-core/interfaces/IHooks.sol";
import {BalanceDelta} from "v4-core/types/BalanceDelta.sol";
import {toBalanceDelta} from "v4-core/types/BalanceDelta.sol";

contract TestToken is IERC20 {
    string public name = "Test USDC";
    string public symbol = "tUSDC";
    uint8 public decimals = 6;
    uint256 public override totalSupply;
    mapping(address => uint256) public override balanceOf;
    mapping(address => mapping(address => uint256)) public override allowance;

    function mint(address recipient, uint256 amount) external {
        totalSupply += amount;
        balanceOf[recipient] += amount;
        emit Transfer(address(0), recipient, amount);
    }

    function transfer(address recipient, uint256 amount) external override returns (bool) {
        _transfer(msg.sender, recipient, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external override returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address sender, address recipient, uint256 amount)
        external
        override
        returns (bool)
    {
        uint256 permitted = allowance[sender][msg.sender];
        require(permitted >= amount, "allowance");
        allowance[sender][msg.sender] = permitted - amount;
        _transfer(sender, recipient, amount);
        return true;
    }

    function _transfer(address sender, address recipient, uint256 amount) internal {
        require(balanceOf[sender] >= amount, "balance");
        balanceOf[sender] -= amount;
        balanceOf[recipient] += amount;
        emit Transfer(sender, recipient, amount);
    }
}

contract TestRunHook {
    address public immutable poolManager;
    address public immutable arbitrageur;

    constructor(address manager_, address arbitrageur_) {
        poolManager = manager_;
        arbitrageur = arbitrageur_;
    }

    function setExecutionEnabled(bool) external {}
    function setPoolAllowed(PoolId, bool) external {}
}

contract UnauthorizedCaller {
    function refund(Arbitrageur target, bytes32 runId) external {
        target.refundUnused(runId);
    }

    function settle(Arbitrageur target, bytes32 runId, uint128 proceeds) external {
        target.settleRun(runId, proceeds);
    }
}

/// @dev Minimal PoolManager double that exercises Arbitrageur's real unlock callback path.
contract TestPoolManager {
    uint128 public outputAmount;

    function setOutputAmount(uint128 amount) external {
        outputAmount = amount;
    }

    function unlock(bytes calldata data) external returns (bytes memory) {
        return IUnlockCallback(msg.sender).unlockCallback(data);
    }

    function swap(PoolKey memory, IPoolManager.SwapParams memory params, bytes calldata)
        external
        view
        returns (BalanceDelta)
    {
        uint128 inputAmount = uint128(uint256(-params.amountSpecified));
        int128 inputDelta = -int128(inputAmount);
        int128 outputDelta = int128(outputAmount);
        return params.zeroForOne
            ? toBalanceDelta(inputDelta, outputDelta)
            : toBalanceDelta(outputDelta, inputDelta);
    }

    function sync(Currency) external pure {}

    function settle() external pure returns (uint256) {
        return 0;
    }

    function take(Currency currency, address recipient, uint256 amount) external {
        IERC20(Currency.unwrap(currency)).transfer(recipient, amount);
    }
}

contract ArbitrageurAccountingTest {
    using PoolIdLibrary for PoolKey;

    uint128 private constant PRINCIPAL = 100_000_000;
    TestToken private usdc;
    TestToken private otherToken;
    TestPoolManager private manager;
    Arbitrageur private arbitrageur;
    PoolKey private poolKey;

    function setUp() public {
        usdc = new TestToken();
        manager = new TestPoolManager();
        arbitrageur = new Arbitrageur(
            IERC20(address(usdc)), IPoolManager(address(manager)), address(this), address(this), PRINCIPAL
        );
        TestRunHook hook = new TestRunHook(address(manager), address(arbitrageur));
        arbitrageur.setHook(IRunHook(address(hook)));

        otherToken = new TestToken();
        (Currency currency0, Currency currency1) = address(usdc) < address(otherToken)
            ? (Currency.wrap(address(usdc)), Currency.wrap(address(otherToken)))
            : (Currency.wrap(address(otherToken)), Currency.wrap(address(usdc)));
        poolKey = PoolKey({
            currency0: currency0,
            currency1: currency1,
            fee: 3000,
            tickSpacing: 60,
            hooks: IHooks(address(hook))
        });
        arbitrageur.setTokenAllowed(address(usdc), true);
        arbitrageur.setTokenAllowed(address(otherToken), true);
        arbitrageur.setPoolAllowed(poolKey, true);
    }

    function testRefundReturnsPrincipalWithoutCreatingClaim() public {
        _createRun(keccak256("refund"));

        arbitrageur.refundUnused(keccak256("refund"));

        (,,,,, uint128 principalRecovered,, uint128 claimCredit, Arbitrageur.RunState state) =
            arbitrageur.runs(keccak256("refund"));
        require(principalRecovered == PRINCIPAL, "principal not recovered");
        require(claimCredit == 0, "unexpected claim credit");
        require(state == Arbitrageur.RunState.Refunded, "wrong terminal state");
        require(arbitrageur.totalClaimable() == 0, "claim total changed");
        require(usdc.balanceOf(address(this)) == PRINCIPAL, "refund not received");
        require(usdc.balanceOf(address(arbitrageur)) >= arbitrageur.totalClaimable(), "claims unbacked");
    }

    function testDuplicateRunIdIsRejected() public {
        bytes32 runId = keccak256("duplicate");
        _createRun(runId);

        bool reverted;
        try arbitrageur.createRun(runId, PRINCIPAL, poolKey) {} catch {
            reverted = true;
        }
        require(reverted, "duplicate run accepted");
    }

    function testOnlyOperatorCanRefund() public {
        bytes32 runId = keccak256("access-control");
        _createRun(runId);
        UnauthorizedCaller caller = new UnauthorizedCaller();

        bool reverted;
        try caller.settle(arbitrageur, runId, 0) {} catch {
            reverted = true;
        }
        require(reverted, "unauthorized refund accepted");
    }

    function testClaimCannotExceedRecordedCredit() public {
        bool reverted;
        try arbitrageur.claim(address(this)) {} catch {
            reverted = true;
        }
        require(reverted, "claim without credit accepted");
        require(arbitrageur.totalClaimable() == 0, "claim total changed");
    }

    function testUnlockSwapAndProfitableSettlementBackClaim() public {
        bytes32 runId = keccak256("profitable-settlement");
        _createRun(runId);
        manager.setOutputAmount(2 ether);
        otherToken.mint(address(manager), 2 ether);

        uint256 output = arbitrageur.executeArbitrage(
            runId, poolKey, address(usdc) == Currency.unwrap(poolKey.currency0), 80_000_000, 1 ether,
            block.timestamp + 60
        );
        require(output == 2 ether, "wrong swap output");
        require(usdc.balanceOf(address(this)) == 20_000_000, "unused principal not returned");

        usdc.mint(address(this), 90_000_000);
        usdc.approve(address(arbitrageur), 90_000_000);
        arbitrageur.settleRun(runId, 90_000_000);

        (,,,,, uint128 recovered, uint128 shortfall, uint128 credit, Arbitrageur.RunState state) =
            arbitrageur.runs(runId);
        require(state == Arbitrageur.RunState.Settled, "not settled");
        require(recovered == PRINCIPAL && shortfall == 0, "principal accounting mismatch");
        require(credit == 10_000_000, "profit credit mismatch");
        require(arbitrageur.totalClaimable() == credit, "claim total mismatch");
        require(usdc.balanceOf(address(arbitrageur)) == credit, "claim not backed");

        arbitrageur.claim(address(this));
        require(arbitrageur.totalClaimable() == 0, "claim total not reduced");
        require(usdc.balanceOf(address(arbitrageur)) == 0, "claim funds remain");
    }

    function testZeroProceedsSettlementRecordsFullShortfall() public {
        bytes32 runId = keccak256("zero-proceeds");
        _createRun(runId);
        manager.setOutputAmount(1 ether);
        otherToken.mint(address(manager), 1 ether);
        arbitrageur.executeArbitrage(
            runId, poolKey, address(usdc) == Currency.unwrap(poolKey.currency0), 80_000_000, 1,
            block.timestamp + 60
        );

        arbitrageur.settleRun(runId, 0);

        (,,,,, uint128 recovered, uint128 shortfall, uint128 credit, Arbitrageur.RunState state) =
            arbitrageur.runs(runId);
        require(state == Arbitrageur.RunState.Settled, "not settled");
        require(recovered == 20_000_000, "wrong recovered principal");
        require(shortfall == 80_000_000, "wrong recorded shortfall");
        require(credit == 0 && arbitrageur.totalClaimable() == 0, "zero proceeds created credit");
    }

    function testOperatorOnlySettlement() public {
        bytes32 runId = keccak256("settlement-access");
        _createRun(runId);
        manager.setOutputAmount(1 ether);
        otherToken.mint(address(manager), 1 ether);
        arbitrageur.executeArbitrage(
            runId, poolKey, address(usdc) == Currency.unwrap(poolKey.currency0), 80_000_000, 1,
            block.timestamp + 60
        );
        UnauthorizedCaller caller = new UnauthorizedCaller();
        bool reverted;
        try caller.refund(arbitrageur, runId) {} catch {
            reverted = true;
        }
        require(reverted, "unauthorized operator action accepted");
    }

    function _createRun(bytes32 runId) private {
        usdc.mint(address(this), PRINCIPAL);
        usdc.approve(address(arbitrageur), PRINCIPAL);
        arbitrageur.createRun(runId, PRINCIPAL, poolKey);
    }
}

