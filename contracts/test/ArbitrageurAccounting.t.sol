// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Arbitrageur, IRunHook} from "../src/Arbitrageur.sol";
import {IPoolManager} from "v4-core/interfaces/IPoolManager.sol";
import {Currency} from "v4-core/types/Currency.sol";
import {PoolKey} from "v4-core/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/types/PoolId.sol";
import {IHooks} from "v4-core/interfaces/IHooks.sol";

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
}

contract ArbitrageurAccountingTest {
    using PoolIdLibrary for PoolKey;

    uint128 private constant PRINCIPAL = 100_000_000;
    TestToken private usdc;
    Arbitrageur private arbitrageur;
    PoolKey private poolKey;

    function setUp() public {
        usdc = new TestToken();
        address manager = address(0xBEEF);
        arbitrageur = new Arbitrageur(
            IERC20(address(usdc)), IPoolManager(manager), address(this), address(this), PRINCIPAL
        );
        TestRunHook hook = new TestRunHook(manager, address(arbitrageur));
        arbitrageur.setHook(IRunHook(address(hook)));

        TestToken otherToken = new TestToken();
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
        try caller.refund(arbitrageur, runId) {} catch {
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

    function _createRun(bytes32 runId) private {
        usdc.mint(address(this), PRINCIPAL);
        usdc.approve(address(arbitrageur), PRINCIPAL);
        arbitrageur.createRun(runId, PRINCIPAL, poolKey);
    }
}

