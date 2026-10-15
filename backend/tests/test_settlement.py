from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.db import Base, make_engine
from arbitmint.models import Run, RunTransition, SideEffectIntent, SimulatorRecord
from arbitmint.settlement import (
    SettlementCoordinator,
    SettlementError,
    SettlementEvidence,
    SettlementUncertain,
)
from arbitmint.state_machine import RunRepository, RunState


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def sold_run(sessions: sessionmaker[Session], *, proceeds: int) -> str:
    unique = uuid4().hex
    run = RunRepository(sessions).create(
        idempotency_key=unique,
        user_address="0x" + "11" * 20,
        chain_id=1301,
        chain_run_id="0x" + unique + "00" * 16,
        principal_amount=100,
        token_in="0x" + "22" * 20,
        token_out="0x" + "33" * 20,
        token_in_decimals=6,
        token_out_decimals=18,
        pool_key={"fee": 3000},
        input_snapshot={},
    )
    with sessions() as session, session.begin():
        stored = session.get(Run, run.id)
        assert stored is not None
        stored.amount_in = Decimal(80)
        stored.acquired_amount = Decimal(50)
        session.add(
            SimulatorRecord(
                run_id=run.id,
                simulator_reference=f"sim_settlement_{unique}",
                status="SUCCESS",
                input_quantity=Decimal(50),
                sold_quantity=Decimal(50),
                unsold_quantity=Decimal(0),
                gross_proceeds=Decimal(proceeds),
                fees=Decimal(0),
                net_proceeds=Decimal(proceeds),
                latency_ms=1,
                configuration={"mode": "deterministic"},
                captured_inputs={"quantity": 50},
                created_at=datetime.now(UTC),
            )
        )
    repository = RunRepository(sessions)
    repository.transition(run.id, RunState.FUNDED, actor="test", reason="funded", evidence={})
    repository.transition(run.id, RunState.EXECUTED, actor="test", reason="executed", evidence={})
    repository.transition(run.id, RunState.SOLD, actor="test", reason="simulated", evidence={})
    return run.id


class FakeGateway:
    def __init__(self, *, mismatch: bool = False, timeout: bool = False) -> None:
        self.mismatch = mismatch
        self.timeout = timeout
        self.calls: list[tuple[str, int, str | None]] = []

    def settle_run(
        self,
        *,
        chain_run_id: str,
        proceeds: int,
        idempotency_key: str,
        existing_transaction_hash: str | None,
        before_broadcast: Callable[[str, int], None],
    ) -> SettlementEvidence:
        self.calls.append((chain_run_id, proceeds, existing_transaction_hash))
        if self.timeout:
            raise TimeoutError("simulated timeout")
        tx_hash = "0x" + "ab" * 32
        if existing_transaction_hash is None:
            before_broadcast(tx_hash, 7)
        received = proceeds + (1 if self.mismatch else 0)
        return SettlementEvidence(
            transaction_hash=tx_hash,
            block_number=12,
            confirmed=True,
            run_is_settled_onchain=True,
            received_usdc=received,
            principal_recovered=20 + min(proceeds, 80),
            shortfall=max(0, 80 - proceeds),
            claim_credit=max(0, proceeds - 80),
            contract_usdc_balance=max(0, proceeds - 80),
            total_claimable=max(0, proceeds - 80),
        )


def test_zero_proceeds_settlement_records_full_spent_principal_shortfall(
    sessions: sessionmaker[Session],
) -> None:
    run_id = sold_run(sessions, proceeds=0)
    gateway = FakeGateway()
    coordinator = SettlementCoordinator(sessions, gateway)

    evidence = coordinator.settle(run_id)
    replay = coordinator.settle(run_id)

    assert evidence.received_usdc == 0
    assert evidence.principal_recovered == 20
    assert evidence.shortfall == 80
    assert evidence.claim_credit == 0
    assert replay == evidence
    assert len(gateway.calls) == 1
    with sessions() as session:
        run = session.get(Run, run_id)
        transitions = session.scalars(
            select(RunTransition).where(RunTransition.run_id == run_id)
        ).all()
    assert run is not None
    assert run.state == RunState.SETTLED.value
    assert int(run.principal_recovered or 0) == 20
    assert int(run.shortfall or 0) == 80
    assert int(run.credited_amount or 0) == 0
    assert [t.after_state for t in transitions][-1] == RunState.SETTLED.value


def test_profit_credit_requires_confirmed_backed_evidence(sessions: sessionmaker[Session]) -> None:
    run_id = sold_run(sessions, proceeds=100)
    evidence = SettlementCoordinator(sessions, FakeGateway()).settle(run_id)
    assert (evidence.principal_recovered, evidence.shortfall, evidence.claim_credit) == (100, 0, 20)
    with sessions() as session:
        run = session.get(Run, run_id)
        intent = session.scalar(select(SideEffectIntent).where(SideEffectIntent.run_id == run_id))
    assert run is not None and run.state == RunState.SETTLED.value
    assert intent is not None and intent.status == "COMPLETED"


def test_uncertain_and_invalid_settlement_evidence_do_not_advance_run(
    sessions: sessionmaker[Session],
) -> None:
    run_id = sold_run(sessions, proceeds=100)
    with pytest.raises(SettlementUncertain):
        SettlementCoordinator(sessions, FakeGateway(timeout=True)).settle(run_id)
    with sessions() as session:
        intent = session.scalar(select(SideEffectIntent).where(SideEffectIntent.run_id == run_id))
        run = session.get(Run, run_id)
    assert intent is not None and intent.status == "PENDING"
    assert run is not None and run.state == RunState.SOLD.value

    run_id = sold_run(sessions, proceeds=100)
    with pytest.raises(SettlementError, match="different amount"):
        SettlementCoordinator(sessions, FakeGateway(mismatch=True)).settle(run_id)
    with sessions() as session:
        intent = session.scalar(select(SideEffectIntent).where(SideEffectIntent.run_id == run_id))
        run = session.get(Run, run_id)
    assert intent is not None and intent.status == "PENDING"
    assert intent.sanitized_error == "SETTLEMENT_EVIDENCE_REQUIRES_RECONCILIATION"
    assert run is not None and run.state == RunState.SOLD.value
