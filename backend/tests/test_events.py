from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.db import Base, make_engine
from arbitmint.events import ConfirmedEventListener
from arbitmint.models import ChainEvent, ListenerCursor, Run, RunTransition
from arbitmint.state_machine import RunRepository, RunState


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_listener_waits_for_confirmations_then_journals_event_once(
    sessions: sessionmaker[Session],
) -> None:
    unique = uuid4().hex
    chain_run_id = "0x" + unique + "00" * 16
    run = RunRepository(sessions).create(
        idempotency_key=unique,
        user_address="0x" + "11" * 20,
        chain_id=1301,
        chain_run_id=chain_run_id,
        principal_amount=100,
        token_in="0x" + "22" * 20,
        token_out="0x" + "33" * 20,
        token_in_decimals=6,
        token_out_decimals=18,
        pool_key={},
        input_snapshot={},
    )
    RunRepository(sessions).transition(
        run.id, RunState.FUNDED, actor="test", reason="funded", evidence={}
    )
    log = {
        "transactionHash": bytes.fromhex("ab" * 32),
        "blockHash": bytes.fromhex("cd" * 32),
        "blockNumber": 4,
        "logIndex": 2,
        "args": {"runId": bytes.fromhex(chain_run_id[2:]), "amountIn": 80, "amountOut": 45},
    }

    class Event:
        def get_logs(self, *, from_block: int, to_block: int) -> list[dict[str, object]]:
            return [log] if from_block <= 4 <= to_block else []

    contract = SimpleNamespace(
        w3=SimpleNamespace(eth=SimpleNamespace(block_number=4)),
        events=SimpleNamespace(
            RunExecuted=lambda: Event(), RunSettled=lambda: Event(), RunRefunded=lambda: Event()
        ),
    )
    listener = ConfirmedEventListener(
        sessions=sessions,
        contract=contract,  # type: ignore[arg-type]
        chain_id=1301,
        contract_address="0x" + "44" * 20,
        start_block=4,
        confirmation_depth=2,
        read_run_state=lambda _run_id: 3,
    )

    assert listener.poll_once() == 0  # block 4 is not yet sufficiently confirmed
    contract.w3.eth.block_number = 5
    assert listener.poll_once() == 1
    assert listener.poll_once() == 0
    with sessions() as session:
        updated = session.get(Run, run.id)
        events = session.scalars(select(ChainEvent)).all()
        cursor = session.get(ListenerCursor, (1301, ("0x" + "44" * 20)))
        transitions = session.scalars(
            select(RunTransition).where(RunTransition.run_id == run.id)
        ).all()
    assert updated is not None and updated.state == RunState.EXECUTED.value
    assert int(updated.amount_in or 0) == 80 and int(updated.acquired_amount or 0) == 45
    assert len(events) == 1 and events[0].confirmed is True
    assert cursor is not None and cursor.next_block == 5
    assert transitions[-1].after_state == RunState.EXECUTED.value
