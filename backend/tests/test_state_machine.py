from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.db import Base, make_engine
from arbitmint.models import Run, RunTransition
from arbitmint.state_machine import (
    IdempotencyConflict,
    InvalidTransition,
    RunRepository,
    RunState,
)


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def new_run(
    repository: RunRepository,
    *,
    key: str = "request-1",
    chain_run_id: str = "0x" + "01" * 32,
    principal_amount: int = 1_000_000,
    input_snapshot: dict[str, object] | None = None,
) -> Run:
    return repository.create(
        idempotency_key=key,
        user_address="0x" + "11" * 20,
        chain_id=1301,
        chain_run_id=chain_run_id,
        principal_amount=principal_amount,
        token_in="0x" + "22" * 20,
        token_out="0x" + "33" * 20,
        token_in_decimals=6,
        token_out_decimals=18,
        pool_key={"fee": 3000, "tick_spacing": 60},
        input_snapshot=input_snapshot or {"quote_block": 123, "estimated_net_profit": -12},
    )


def test_create_persists_initial_state_idempotency_and_transition(sessions: sessionmaker[Session]) -> None:
    repository = RunRepository(sessions)
    created = new_run(repository)

    replay = new_run(repository)

    assert replay.id == created.id
    assert replay.state == RunState.CREATED.value
    assert int(replay.principal_amount) == 1_000_000
    with sessions() as session:
        transitions = session.scalars(
            select(RunTransition).where(RunTransition.run_id == created.id)
        ).all()
    assert [(item.before_state, item.after_state) for item in transitions] == [("NONE", "CREATED")]
    assert transitions[0].evidence == {"opportunity_id": None}


def test_idempotency_key_cannot_be_reused_for_different_request(
    sessions: sessionmaker[Session],
) -> None:
    repository = RunRepository(sessions)
    new_run(repository)

    with pytest.raises(IdempotencyConflict):
        new_run(repository, principal_amount=2_000_000)


def test_chain_run_id_cannot_be_assigned_to_multiple_runs(sessions: sessionmaker[Session]) -> None:
    repository = RunRepository(sessions)
    new_run(repository)

    with pytest.raises(IdempotencyConflict, match="chain_run_id"):
        new_run(repository, key="request-2")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chain_id": 1}, "only Unichain Sepolia"),
        ({"chain_run_id": "0x" + "zz" * 32}, "32-byte hex"),
        ({"user_address": "not-an-address"}, "20-byte hex address"),
        ({"token_in_decimals": 256}, "decimals"),
    ],
)
def test_create_rejects_invalid_chain_and_identifiers(
    sessions: sessionmaker[Session], overrides: dict[str, object], message: str
) -> None:
    repository = RunRepository(sessions)
    arguments: dict[str, object] = {
        "idempotency_key": "invalid-request",
        "user_address": "0x" + "11" * 20,
        "chain_id": 1301,
        "chain_run_id": "0x" + "44" * 32,
        "principal_amount": 10,
        "token_in": "0x" + "22" * 20,
        "token_out": "0x" + "33" * 20,
        "token_in_decimals": 6,
        "token_out_decimals": 18,
        "pool_key": {},
        "input_snapshot": {},
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        repository.create(**arguments)  # type: ignore[arg-type]


def test_create_rejects_floating_point_run_inputs(sessions: sessionmaker[Session]) -> None:
    repository = RunRepository(sessions)

    with pytest.raises(TypeError, match="floating-point"):
        new_run(repository, input_snapshot={"price": 1.25})


def test_transitions_are_validated_and_audited(sessions: sessionmaker[Session]) -> None:
    repository = RunRepository(sessions)
    run = new_run(repository)
    funded = repository.transition(
        run.id,
        RunState.FUNDED,
        actor="funding_adapter",
        reason="BALANCE_CONFIRMED",
        evidence={"provider_status": "CONFIRMED", "observed_balance": 1_000_000},
    )
    assert funded.state == RunState.FUNDED.value

    with pytest.raises(InvalidTransition, match="FUNDED -> SOLD"):
        repository.transition(
            run.id,
            RunState.SOLD,
            actor="test",
            reason="SKIP_EXECUTION",
            evidence={},
        )

    with sessions() as session:
        transitions = session.scalars(
            select(RunTransition)
            .where(RunTransition.run_id == run.id)
            .order_by(RunTransition.id)
        ).all()
    assert [(item.before_state, item.after_state) for item in transitions] == [
        ("NONE", "CREATED"),
        ("CREATED", "FUNDED"),
    ]
    assert transitions[-1].actor == "funding_adapter"
    assert transitions[-1].evidence["observed_balance"] == 1_000_000


def test_transition_rejects_float_evidence_and_negative_claim_amount(
    sessions: sessionmaker[Session],
) -> None:
    repository = RunRepository(sessions)
    run = new_run(repository)

    with pytest.raises(TypeError, match="floating-point"):
        repository.transition(
            run.id,
            RunState.FUNDED,
            actor="test",
            reason="FLOAT_EVIDENCE",
            evidence={"balance": 1.5},
        )

    with pytest.raises(ValueError, match="cannot be negative"):
        repository.transition(
            run.id,
            RunState.FUNDED,
            actor="test",
            reason="NEGATIVE_CREDIT",
            evidence={},
            fields={"credited_amount": -1},
        )


def test_get_can_scope_a_run_to_its_user(sessions: sessionmaker[Session]) -> None:
    repository = RunRepository(sessions)
    run = new_run(repository)

    assert repository.get(run.id, user_address="0x" + "11" * 20) is not None
    assert repository.get(run.id, user_address="0x" + "ff" * 20) is None
