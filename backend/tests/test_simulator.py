from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.db import Base, make_engine
from arbitmint.models import Run, SimulatorRecord
from arbitmint.simulator import DeterministicVenueSimulator, SimulatorConfig
from arbitmint.state_machine import RunRepository, RunState


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def executed_run(sessions: sessionmaker[Session], run_id: str = "run-sim") -> str:
    unique = uuid4().hex
    repository = RunRepository(sessions)
    run = repository.create(
        idempotency_key=run_id,
        user_address="0x" + "11" * 20,
        chain_id=1301,
        chain_run_id="0x" + unique + "00" * 16,
        principal_amount=1_000_000,
        token_in="0x" + "22" * 20,
        token_out="0x" + "33" * 20,
        token_in_decimals=6,
        token_out_decimals=18,
        pool_key={"fee": 3000},
        input_snapshot={"source": "test"},
    )
    with sessions() as session, session.begin():
        stored = session.get(Run, run.id)
        assert stored is not None
        stored.amount_in = Decimal(80)
        stored.acquired_amount = Decimal(50)
    repository.transition(run.id, RunState.FUNDED, actor="test", reason="funded", evidence={})
    repository.transition(run.id, RunState.EXECUTED, actor="test", reason="executed", evidence={})
    return run.id


def test_simulation_is_deterministic_and_records_full_inputs(sessions: sessionmaker[Session]) -> None:
    run_id = executed_run(sessions)
    simulator = DeterministicVenueSimulator(
        sessions,
        SimulatorConfig(
            price_numerator=3,
            price_denominator=2,
            max_quantity=100,
            spread_bps=100,
            fee_bps=200,
            latency_ms=25,
        ),
    )

    result = simulator.sell(run_id, quantity=50)
    replay = simulator.sell(run_id, quantity=50)

    assert result == replay
    assert result.simulated is True
    assert (result.gross_proceeds, result.fees, result.net_proceeds) == (75, 1, 73)
    assert result.captured_inputs["quantity"] == 50
    with sessions() as session:
        record = session.get(SimulatorRecord, run_id)
        run = session.get(Run, run_id)
    assert record is not None and record.configuration["fee_bps"] == 200
    assert run is not None and run.state == RunState.SOLD.value


def test_partial_depth_and_failure_are_persisted(sessions: sessionmaker[Session]) -> None:
    partial_id = executed_run(sessions, "partial")
    fail_id = executed_run(sessions, "failed")
    simulator = DeterministicVenueSimulator(
        sessions,
        SimulatorConfig(
            price_numerator=2,
            price_denominator=1,
            max_quantity=20,
            failure_run_ids=(fail_id,),
        ),
    )

    partial = simulator.sell(partial_id, quantity=50)
    failed = simulator.sell(fail_id, quantity=50)

    assert (partial.status, partial.sold_quantity, partial.unsold_quantity) == ("PARTIAL", 20, 30)
    assert partial.net_proceeds == 40
    assert (failed.status, failed.net_proceeds, failed.unsold_quantity) == ("FAILED", 0, 50)
    with sessions() as session:
        assert session.get(Run, fail_id).state == RunState.STUCK.value  # type: ignore[union-attr]


def test_simulator_rejects_quantity_mismatch_and_mutated_replay_config(
    sessions: sessionmaker[Session],
) -> None:
    run_id = executed_run(sessions)
    first = DeterministicVenueSimulator(sessions, SimulatorConfig(1, 1, 100))
    first.sell(run_id, quantity=50)
    with pytest.raises(ValueError, match="confirmed acquired"):
        first.sell(run_id, quantity=49)
    changed = DeterministicVenueSimulator(sessions, SimulatorConfig(2, 1, 100))
    with pytest.raises(ValueError, match="different immutable"):
        changed.sell(run_id, quantity=50)


@pytest.mark.parametrize("config", [
    SimulatorConfig(1, 1, 0),
    SimulatorConfig(1, 1, 10, fee_bps=10_001),
    SimulatorConfig(1, 1, 10, price_move_bps=-10_000),
])
def test_simulator_rejects_unsafe_configuration(config: SimulatorConfig) -> None:
    with pytest.raises(ValueError):
        config.validate()
