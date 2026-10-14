from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol, cast

from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from web3 import HTTPProvider, Web3
from web3.contract.contract import Contract
from web3.exceptions import TransactionNotFound
from web3.types import TxParams

from arbitmint.models import (
    Run,
    RunTransition,
    SideEffectIntent,
    SimulatorRecord,
    TransactionRecord,
)
from arbitmint.state_machine import InvalidTransition, RunState


class SettlementError(RuntimeError):
    pass


class SettlementUncertain(SettlementError):
    pass


class SettlementRejected(SettlementError):
    pass


@dataclass(frozen=True)
class SettlementEvidence:
    transaction_hash: str
    block_number: int
    confirmed: bool
    run_is_settled_onchain: bool
    received_usdc: int
    principal_recovered: int
    shortfall: int
    claim_credit: int
    contract_usdc_balance: int
    total_claimable: int


class SettlementGateway(Protocol):
    def settle_run(
        self,
        *,
        chain_run_id: str,
        proceeds: int,
        idempotency_key: str,
        existing_transaction_hash: str | None,
        before_broadcast: Callable[[str, int], None],
    ) -> SettlementEvidence: ...


def _now() -> datetime:
    return datetime.now(UTC)


class SettlementCoordinator:
    """Persist intent, execute/reconcile on-chain settlement, then transition state."""

    def __init__(self, sessions: sessionmaker[Session], gateway: SettlementGateway) -> None:
        self._sessions = sessions
        self._gateway = gateway

    def settle(self, run_id: str) -> SettlementEvidence:
        intent_key = "settle:" + hashlib.sha256(run_id.encode()).hexdigest()
        with self._sessions() as session, session.begin():
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            simulator = session.get(SimulatorRecord, run_id)
            if simulator is None or simulator.status not in {"SUCCESS", "PARTIAL"}:
                raise SettlementError("settlement requires a durable successful simulator result")
            if run.state not in {RunState.SOLD.value, RunState.STUCK.value}:
                raise SettlementError(f"cannot settle a run in {run.state}")
            proceeds = int(simulator.net_proceeds)
            if proceeds < 0 or proceeds > 2**128 - 1:
                raise SettlementError("simulated proceeds are outside contract amount bounds")
            chain_run_id = run.chain_run_id
            request = {"chain_run_id": chain_run_id, "proceeds": proceeds}
            intent = session.scalar(
                select(SideEffectIntent)
                .where(SideEffectIntent.run_id == run_id, SideEffectIntent.operation == "SETTLE")
                .with_for_update()
            )
            if intent is None:
                intent = SideEffectIntent(
                    run_id=run_id,
                    operation="SETTLE",
                    idempotency_key=intent_key,
                    status="PENDING",
                    request=request,
                    created_at=_now(),
                    updated_at=_now(),
                )
                session.add(intent)
                session.flush()
            elif intent.request != request:
                raise SettlementError("settlement request conflicts with its persisted intent")
            if intent.status == "COMPLETED":
                evidence = _evidence(intent.result)
                if run.state != RunState.SETTLED.value:
                    raise SettlementError("completed settlement intent conflicts with persisted run state")
                return evidence
            existing_tx_hash = intent.tx_hash
            if intent.status == "SUBMITTING" and existing_tx_hash is None:
                raise SettlementUncertain(
                    "settlement submission was interrupted before its transaction hash was recorded; reconcile manually"
                )
            intent.status = "SUBMITTING"
            intent.updated_at = _now()

        try:
            evidence = self._gateway.settle_run(
                chain_run_id=chain_run_id,
                proceeds=proceeds,
                idempotency_key=intent_key,
                existing_transaction_hash=existing_tx_hash,
                before_broadcast=lambda tx_hash, nonce: self._record_tx(
                    run_id, tx_hash, nonce
                ),
            )
        except TimeoutError as exc:
            self._mark_intent(run_id, "PENDING", sanitized_error="SETTLEMENT_TIMEOUT")
            raise SettlementUncertain("settlement outcome is uncertain; reconcile before retry") from exc
        except SettlementRejected as exc:
            self._mark_intent(run_id, "FAILED", sanitized_error="SETTLEMENT_REVERTED")
            raise SettlementError("settlement transaction reverted on-chain") from exc
        except Exception as exc:
            self._mark_intent(run_id, "PENDING", sanitized_error="SETTLEMENT_OUTCOME_UNCERTAIN")
            raise SettlementUncertain("settlement outcome is uncertain; reconcile before retry") from exc

        self._validate_evidence(run, proceeds, evidence)
        self._complete_intent_and_transition(run_id, proceeds, evidence)
        return evidence

    def _validate_evidence(self, run: Run, proceeds: int, evidence: SettlementEvidence) -> None:
        numeric = (
            evidence.block_number,
            evidence.received_usdc,
            evidence.principal_recovered,
            evidence.shortfall,
            evidence.claim_credit,
            evidence.contract_usdc_balance,
            evidence.total_claimable,
        )
        if any(type(value) is not int or value < 0 for value in numeric):
            raise SettlementError("settlement gateway returned invalid numeric evidence")
        if not evidence.confirmed or not evidence.run_is_settled_onchain:
            raise SettlementUncertain("settlement is not confirmed on-chain")
        if evidence.received_usdc != proceeds:
            raise SettlementError("contract received a different amount than the simulator result")
        if evidence.contract_usdc_balance < evidence.total_claimable:
            raise SettlementError("on-chain totalClaimable exceeds actual contract USDC balance")
        if run.amount_in is None:
            raise SettlementError("confirmed swap input is missing from the run ledger")
        spent = int(run.amount_in)
        expected_recovered = int(run.principal_amount) - spent + min(proceeds, spent)
        expected_shortfall = max(0, spent - proceeds)
        expected_credit = max(0, proceeds - spent)
        if (
            evidence.principal_recovered != expected_recovered
            or evidence.shortfall != expected_shortfall
            or evidence.claim_credit != expected_credit
        ):
            raise SettlementError("on-chain principal and credit accounting differs from recorded inputs")

    def _complete_intent_and_transition(
        self, run_id: str, proceeds: int, evidence: SettlementEvidence
    ) -> None:
        now = _now()
        evidence_payload = asdict(evidence)
        with self._sessions() as session, session.begin():
            intent = session.scalar(
                select(SideEffectIntent)
                .where(SideEffectIntent.run_id == run_id, SideEffectIntent.operation == "SETTLE")
                .with_for_update()
            )
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if intent is None or run is None:
                raise RuntimeError("settlement records disappeared")
            intent.status = "COMPLETED"
            intent.result = evidence_payload
            intent.reference = evidence.transaction_hash
            intent.tx_hash = evidence.transaction_hash
            intent.updated_at = now
            before_state = run.state
            if before_state == RunState.SETTLED.value:
                return
            if before_state not in {RunState.SOLD.value, RunState.STUCK.value}:
                raise InvalidTransition(f"{before_state} -> SETTLED is not allowed")
            run.state = RunState.SETTLED.value
            run.simulated_proceeds = Decimal(proceeds)
            run.principal_recovered = Decimal(evidence.principal_recovered)
            run.shortfall = Decimal(evidence.shortfall)
            run.credited_amount = Decimal(evidence.claim_credit)
            run.state_reason = "CONFIRMED_ONCHAIN_SETTLEMENT"
            run.state_evidence = evidence_payload
            run.updated_at = now
            session.add(
                RunTransition(
                    run_id=run_id,
                    before_state=before_state,
                    after_state=RunState.SETTLED.value,
                    actor="settlement_coordinator",
                    reason="CONFIRMED_ONCHAIN_SETTLEMENT",
                    evidence=evidence_payload,
                    created_at=now,
                )
            )

    def _mark_intent(self, run_id: str, status: str, *, sanitized_error: str) -> None:
        with self._sessions() as session, session.begin():
            intent = session.scalar(
                select(SideEffectIntent)
                .where(SideEffectIntent.run_id == run_id, SideEffectIntent.operation == "SETTLE")
                .with_for_update()
            )
            if intent is not None:
                intent.status = status
                intent.sanitized_error = sanitized_error
                intent.updated_at = _now()
                if status == "FAILED":
                    intent.tx_hash = None
                    intent.reference = None
                    run = session.get(Run, run_id)
                    if run is not None:
                        tx = session.scalar(
                            select(TransactionRecord)
                            .where(
                                TransactionRecord.run_id == run_id,
                                TransactionRecord.chain_id == run.chain_id,
                                TransactionRecord.operation == "SETTLE",
                            )
                            .order_by(TransactionRecord.id.desc())
                        )
                        if tx is not None:
                            tx.status = "REVERTED"
                            tx.confirmation_status = "FAILED"
                            tx.sanitized_error = sanitized_error

    def _record_tx(self, run_id: str, tx_hash: str, nonce: int) -> None:
        now = _now()
        with self._sessions() as session, session.begin():
            run = session.get(Run, run_id)
            intent = session.scalar(
                select(SideEffectIntent)
                .where(SideEffectIntent.run_id == run_id, SideEffectIntent.operation == "SETTLE")
                .with_for_update()
            )
            if run is None or intent is None:
                raise RuntimeError("settlement intent disappeared before transaction submission")
            if intent.tx_hash is not None and intent.tx_hash.lower() != tx_hash.lower():
                raise SettlementUncertain("a different settlement transaction is already recorded")
            intent.tx_hash = tx_hash
            intent.updated_at = now
            existing = session.scalar(
                select(TransactionRecord).where(
                    TransactionRecord.chain_id == run.chain_id,
                    TransactionRecord.transaction_hash == tx_hash,
                )
            )
            if existing is None:
                session.add(
                    TransactionRecord(
                        run_id=run_id,
                        chain_id=run.chain_id,
                        operation="SETTLE",
                        transaction_hash=tx_hash,
                        nonce=nonce,
                        status="SUBMITTING",
                        submitted_at=now,
                        confirmation_status="PENDING",
                    )
                )
            else:
                existing.status = "SUBMITTING"
                existing.confirmation_status = "PENDING"
                existing.sanitized_error = None


def _evidence(result: dict[str, object] | None) -> SettlementEvidence:
    if result is None:
        raise SettlementError("completed settlement has no stored evidence")
    return SettlementEvidence(**result)  # type: ignore[arg-type]


class Web3SettlementGateway:
    """Submits and confirms Arbitrageur.settleRun on Unichain Sepolia."""

    ARBITRAGEUR_ABI: ClassVar[list[dict[str, object]]] = [
        {
            "type": "function",
            "name": "settleRun",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "runId", "type": "bytes32"}, {"name": "proceeds", "type": "uint128"}],
            "outputs": [],
        },
        {
            "type": "function",
            "name": "runs",
            "stateMutability": "view",
            "inputs": [{"name": "", "type": "bytes32"}],
            "outputs": [
                {"name": "user", "type": "address"},
                {"name": "poolId", "type": "bytes32"},
                {"name": "principal", "type": "uint128"},
                {"name": "amountIn", "type": "uint128"},
                {"name": "amountOut", "type": "uint128"},
                {"name": "principalRecovered", "type": "uint128"},
                {"name": "shortfall", "type": "uint128"},
                {"name": "claimCredit", "type": "uint128"},
                {"name": "state", "type": "uint8"},
            ],
        },
        {"type": "function", "name": "totalClaimable", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]},
        {
            "type": "event",
            "name": "RunSettled",
            "anonymous": False,
            "inputs": [
                {"name": "runId", "type": "bytes32", "indexed": True},
                {"name": "proceeds", "type": "uint256", "indexed": False},
                {"name": "principalRecovered", "type": "uint256", "indexed": False},
                {"name": "shortfall", "type": "uint256", "indexed": False},
                {"name": "claimCredit", "type": "uint256", "indexed": False},
            ],
        },
    ]
    ERC20_ABI: ClassVar[list[dict[str, object]]] = [
        {
            "type": "function",
            "name": "allowance",
            "stateMutability": "view",
            "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
            "outputs": [{"type": "uint256"}],
        },
        {
            "type": "function",
            "name": "balanceOf",
            "stateMutability": "view",
            "inputs": [{"name": "account", "type": "address"}],
            "outputs": [{"type": "uint256"}],
        },
        {
            "type": "event",
            "name": "Transfer",
            "anonymous": False,
            "inputs": [
                {"name": "from", "type": "address", "indexed": True},
                {"name": "to", "type": "address", "indexed": True},
                {"name": "value", "type": "uint256", "indexed": False},
            ],
        },
    ]

    def __init__(
        self,
        *,
        web3: Web3,
        arbitrageur: Contract,
        usdc: Contract,
        operator_account: LocalAccount,
        confirmation_depth: int = 2,
        receipt_timeout: int = 120,
    ) -> None:
        if int(web3.eth.chain_id) != 1301:
            raise ValueError("settlement gateway only supports Unichain Sepolia (chain ID 1301)")
        if confirmation_depth < 1 or receipt_timeout < 1:
            raise ValueError("confirmation depth and receipt timeout must be positive")
        self.web3 = web3
        self.arbitrageur = arbitrageur
        self.usdc = usdc
        self.operator = operator_account
        self.confirmation_depth = confirmation_depth
        self.receipt_timeout = receipt_timeout

    @classmethod
    def from_env(cls) -> Web3SettlementGateway:
        rpc_url = os.environ["UNICHAIN_SEPOLIA_RPC_URL"]
        private_key = os.environ["OPERATOR_PRIVATE_KEY"]
        arbitrageur_address = Web3.to_checksum_address(os.environ["ARBITRAGEUR_ADDRESS"])
        usdc_address = Web3.to_checksum_address(os.environ["TESTNET_USDC_ADDRESS"])
        web3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        from eth_account import Account

        operator = Account.from_key(private_key)
        return cls(
            web3=web3,
            arbitrageur=web3.eth.contract(address=arbitrageur_address, abi=cls.ARBITRAGEUR_ABI),
            usdc=web3.eth.contract(address=usdc_address, abi=cls.ERC20_ABI),
            operator_account=operator,
        )

    def settle_run(
        self,
        *,
        chain_run_id: str,
        proceeds: int,
        idempotency_key: str,
        existing_transaction_hash: str | None,
        before_broadcast: Callable[[str, int], None],
    ) -> SettlementEvidence:
        del idempotency_key  # The durable transaction hash and nonce provide retry reconciliation.
        run_id_bytes = bytes.fromhex(chain_run_id.removeprefix("0x"))
        if len(run_id_bytes) != 32 or not 0 < proceeds <= 2**128 - 1:
            raise SettlementError("invalid on-chain run ID or proceeds amount")
        operator_address = Web3.to_checksum_address(self.operator.address)
        arbitrageur_address = Web3.to_checksum_address(self.arbitrageur.address)
        receipt = None
        if existing_transaction_hash is not None:
            existing_hash = HexBytes(existing_transaction_hash)
            try:
                receipt = self.web3.eth.get_transaction_receipt(existing_hash)
            except TransactionNotFound:
                try:
                    self.web3.eth.get_transaction(existing_hash)
                except TransactionNotFound as exc:
                    raise SettlementUncertain(
                        "recorded transaction is not visible; refusing to submit a duplicate"
                    ) from exc
                try:
                    receipt = self.web3.eth.wait_for_transaction_receipt(
                        existing_hash, timeout=self.receipt_timeout
                    )
                except TimeoutError as exc:
                    raise TimeoutError("settlement transaction confirmation timed out") from exc
        else:
            allowance = int(self.usdc.functions.allowance(operator_address, arbitrageur_address).call())
            if allowance < proceeds:
                raise SettlementRejected("operator must approve the exact settlement amount before settlement")
            nonce = int(self.web3.eth.get_transaction_count(operator_address, "pending"))
            function = self.arbitrageur.functions.settleRun(chain_run_id, proceeds)
            transaction = function.build_transaction(
                cast(
                    TxParams,
                    {
                    "from": operator_address,
                    "nonce": nonce,
                    "chainId": 1301,
                    "gas": int(function.estimate_gas({"from": operator_address}) * 120 // 100),
                    "gasPrice": int(self.web3.eth.gas_price),
                    },
                )
            )
            signed = self.operator.sign_transaction(cast(Any, transaction))
            tx_hash = Web3.to_hex(signed.hash)
            before_broadcast(tx_hash, nonce)
            try:
                self.web3.eth.send_raw_transaction(signed.raw_transaction)
            except Exception as exc:
                raise SettlementUncertain("transaction submission result is uncertain") from exc
            try:
                receipt = self.web3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=self.receipt_timeout
                )
            except TimeoutError as exc:
                raise TimeoutError("settlement transaction confirmation timed out") from exc

        if int(receipt["status"]) != 1:
            raise SettlementRejected("settlement transaction reverted")
        block_number = int(receipt["blockNumber"])
        deadline = time.monotonic() + self.receipt_timeout
        while int(self.web3.eth.block_number) < block_number + self.confirmation_depth - 1:
            if time.monotonic() >= deadline:
                raise TimeoutError("settlement confirmation depth timed out")
            time.sleep(1)
        canonical_block = self.web3.eth.get_block(block_number)
        if Web3.to_hex(canonical_block["hash"]) != Web3.to_hex(receipt["blockHash"]):
            raise SettlementUncertain("settlement receipt was removed by a reorganization")

        from web3.logs import DISCARD

        settled_events = self.arbitrageur.events.RunSettled().process_receipt(receipt, errors=DISCARD)
        matching = [
            event["args"]
            for event in settled_events
            if Web3.to_hex(event["args"]["runId"]).lower() == chain_run_id.lower()
        ]
        if len(matching) != 1 or int(matching[0]["proceeds"]) != proceeds:
            raise SettlementError("confirmed receipt has no matching RunSettled evidence")
        transfer_events = self.usdc.events.Transfer().process_receipt(receipt, errors=DISCARD)
        received = sum(
            int(event["args"]["value"])
            for event in transfer_events
            if Web3.to_checksum_address(event["args"]["from"]) == operator_address
            and Web3.to_checksum_address(event["args"]["to"]) == arbitrageur_address
        )
        if received != proceeds:
            raise SettlementError("receipt does not prove the exact USDC transfer into Arbitrageur")

        run_data = self.arbitrageur.functions.runs(chain_run_id).call()
        total_claimable = int(self.arbitrageur.functions.totalClaimable().call())
        balance = int(self.usdc.functions.balanceOf(arbitrageur_address).call())
        event = matching[0]
        if (
            int(run_data[8]) != 5
            or int(run_data[5]) != int(event["principalRecovered"])
            or int(run_data[6]) != int(event["shortfall"])
            or int(run_data[7]) != int(event["claimCredit"])
            or balance < total_claimable
        ):
            raise SettlementError("confirmed contract state or claim-backing invariant does not match")
        return SettlementEvidence(
            transaction_hash=Web3.to_hex(receipt["transactionHash"]),
            block_number=block_number,
            confirmed=True,
            run_is_settled_onchain=True,
            received_usdc=received,
            principal_recovered=int(event["principalRecovered"]),
            shortfall=int(event["shortfall"]),
            claim_credit=int(event["claimCredit"]),
            contract_usdc_balance=balance,
            total_claimable=total_claimable,
        )
