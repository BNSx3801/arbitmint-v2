from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from web3.contract.contract import Contract

from arbitmint.models import ChainEvent, ListenerCursor, Run, RunTransition
from arbitmint.state_machine import RunState


class EventReadError(RuntimeError):
    pass


class RunStateReader(Protocol):
    def __call__(self, chain_run_id: str) -> int: ...


CHAIN_STATE_BY_EVENT = {
    "RunExecuted": (3, RunState.EXECUTED),
    "RunSettled": (5, RunState.SETTLED),
    "RunRefunded": (6, RunState.FAILED),
}


class ConfirmedEventListener:
    """Polls confirmed logs, journals each log exactly once, then reconciles run state."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        contract: Contract,
        chain_id: int,
        contract_address: str,
        start_block: int,
        confirmation_depth: int,
        read_run_state: RunStateReader,
    ) -> None:
        if chain_id != 1301:
            raise ValueError("only Unichain Sepolia (chain ID 1301) is enabled")
        if confirmation_depth < 1 or start_block < 0:
            raise ValueError("invalid block cursor or confirmation depth")
        self._sessions = sessions
        self._contract = contract
        self._chain_id = chain_id
        self._address = contract_address.lower()
        self._start_block = start_block
        self._confirmation_depth = confirmation_depth
        self._read_run_state = read_run_state

    def poll_once(self) -> int:
        latest = int(self._contract.w3.eth.block_number)
        confirmed_head = latest - self._confirmation_depth + 1
        if confirmed_head < self._start_block:
            return 0
        with self._sessions() as session:
            cursor = session.get(ListenerCursor, (self._chain_id, self._address))
            from_block = self._start_block if cursor is None else cursor.next_block
        if from_block > confirmed_head:
            return 0

        collected: list[tuple[str, Any]] = []
        for event_name in CHAIN_STATE_BY_EVENT:
            event_factory = getattr(self._contract.events, event_name)
            for log in event_factory().get_logs(from_block=from_block, to_block=confirmed_head):
                collected.append((event_name, log))
        collected.sort(key=lambda item: (int(item[1]["blockNumber"]), int(item[1]["logIndex"])))

        inserted = 0
        now = datetime.now(timezone.utc)
        with self._sessions() as session, session.begin():
            cursor = session.get(ListenerCursor, (self._chain_id, self._address))
            if cursor is not None and cursor.next_block != from_block:
                raise EventReadError("listener cursor changed during polling; retry the poll")
            for event_name, log in collected:
                tx_hash = _hex(log["transactionHash"])
                block_hash = _hex(log["blockHash"])
                log_index = int(log["logIndex"])
                duplicate = session.scalar(
                    select(ChainEvent.id).where(
                        ChainEvent.chain_id == self._chain_id,
                        ChainEvent.transaction_hash == tx_hash,
                        ChainEvent.log_index == log_index,
                    )
                )
                if duplicate is not None:
                    continue
                args = _jsonable(dict(log["args"]))
                chain_run_id = _hex(args["runId"]).lower() if "runId" in args else None
                run = None
                if chain_run_id is not None:
                    run = session.scalar(select(Run).where(Run.chain_run_id == chain_run_id))
                    if run is None:
                        raise EventReadError(f"event {event_name} references unknown run {chain_run_id}")

                expected_chain_state, target_state = CHAIN_STATE_BY_EVENT[event_name]
                if chain_run_id is not None:
                    observed_chain_state = self._read_run_state(chain_run_id)
                    if observed_chain_state < expected_chain_state or observed_chain_state not in {3, 4, 5, 6}:
                        raise EventReadError("confirmed event does not match current on-chain run state")

                event = ChainEvent(
                    chain_id=self._chain_id,
                    block_number=int(log["blockNumber"]),
                    block_hash=block_hash,
                    transaction_hash=tx_hash,
                    log_index=log_index,
                    event_name=event_name,
                    run_id=None if run is None else run.id,
                    payload=args,
                    confirmed=True,
                    created_at=now,
                )
                session.add(event)
                if run is not None and run.state != target_state.value:
                    current_state = RunState(run.state)
                    phase = {
                        RunState.CREATED: 0,
                        RunState.FUNDED: 1,
                        RunState.EXECUTED: 2,
                        RunState.SOLD: 3,
                        RunState.SETTLED: 4,
                        RunState.REDEEMED: 5,
                        RunState.FAILED: 5,
                        RunState.STUCK: 4,
                    }
                    if current_state not in phase or phase[target_state] < phase[current_state]:
                        raise EventReadError(
                            f"event {event_name} conflicts with backend state {current_state.value}"
                        )
                    evidence: dict[str, object] = {
                        "transaction_hash": tx_hash,
                        "block_number": int(log["blockNumber"]),
                        "block_hash": block_hash,
                        "log_index": log_index,
                        "confirmed": True,
                    }
                    if event_name == "RunExecuted":
                        run.amount_in = int(args["amountIn"])
                        evidence["amount_out"] = int(args["amountOut"])
                        evidence["amount_in"] = int(args["amountIn"])
                        run.acquired_amount = int(args["amountOut"])
                    elif event_name == "RunSettled":
                        run.simulated_proceeds = int(args["proceeds"])
                        run.principal_recovered = int(args["principalRecovered"])
                        run.shortfall = int(args["shortfall"])
                        run.credited_amount = int(args["claimCredit"])
                        evidence.update(args)
                    if phase[current_state] < phase[target_state] or (
                        current_state == RunState.STUCK and target_state == RunState.SETTLED
                    ):
                        before_state = run.state
                        run.state = target_state.value
                        run.updated_at = now
                        run.state_reason = f"CHAIN_EVENT_{event_name.upper()}"
                        run.state_evidence = evidence
                        session.add(
                            RunTransition(
                                run_id=run.id,
                                before_state=before_state,
                                after_state=target_state.value,
                                actor="chain_event_listener",
                                reason=f"CHAIN_EVENT_{event_name.upper()}",
                                evidence=evidence,
                                created_at=now,
                            )
                        )
                inserted += 1
            if cursor is None:
                session.add(
                    ListenerCursor(
                        chain_id=self._chain_id,
                        contract_address=self._address,
                        next_block=confirmed_head + 1,
                        updated_at=now,
                    )
                )
            else:
                cursor.next_block = confirmed_head + 1
                cursor.updated_at = now
        return inserted


def _hex(value: object) -> str:
    if hasattr(value, "hex"):
        result = value.hex()
        return result if result.startswith("0x") else "0x" + result
    text = str(value)
    return text if text.startswith("0x") else "0x" + text


def _jsonable(value: Any) -> Any:
    if hasattr(value, "hex"):
        return _hex(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported event value {type(value).__name__}")
