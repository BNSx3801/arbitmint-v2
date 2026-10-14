from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.models import IdempotencyKey, Run, RunTransition


class RunState(StrEnum):
    CREATED = "CREATED"
    FUNDED = "FUNDED"
    EXECUTED = "EXECUTED"
    SOLD = "SOLD"
    SETTLED = "SETTLED"
    REDEEMED = "REDEEMED"
    FAILED = "FAILED"
    STUCK = "STUCK"
    LOSS = "LOSS"


ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.FUNDED, RunState.FAILED}),
    RunState.FUNDED: frozenset({RunState.EXECUTED, RunState.FAILED}),
    RunState.EXECUTED: frozenset({RunState.SOLD, RunState.STUCK, RunState.LOSS}),
    RunState.SOLD: frozenset({RunState.SETTLED, RunState.STUCK, RunState.LOSS}),
    RunState.SETTLED: frozenset({RunState.REDEEMED, RunState.STUCK}),
    RunState.REDEEMED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.STUCK: frozenset({RunState.EXECUTED, RunState.SOLD, RunState.SETTLED, RunState.LOSS}),
    RunState.LOSS: frozenset(),
}


class InvalidTransition(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical_hash(value: Any) -> str:
    _validate_json(value)
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_json(value: Any) -> None:
    """Reject non-JSON values and floats before they enter durable audit records."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise TypeError("floating-point values are forbidden in run data")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        for child in value.values():
            _validate_json(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_json(child)
        return
    raise TypeError(f"unsupported run data type: {type(value).__name__}")


class RunRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(
        self,
        *,
        idempotency_key: str,
        user_address: str,
        chain_id: int,
        chain_run_id: str,
        principal_amount: int,
        token_in: str,
        token_out: str,
        token_in_decimals: int,
        token_out_decimals: int,
        pool_key: dict[str, object],
        input_snapshot: dict[str, object],
        opportunity_id: str | None = None,
    ) -> Run:
        if not idempotency_key or len(idempotency_key) > 200:
            raise ValueError("a valid idempotency key is required")
        if type(principal_amount) is not int or principal_amount <= 0:
            raise ValueError("principal_amount must be a positive integer in base units")
        if chain_id != 1301:
            raise ValueError("only Unichain Sepolia (chain ID 1301) is enabled")
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", chain_run_id):
            raise ValueError("chain_run_id must be a 32-byte hex value")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", user_address):
            raise ValueError("user_address must be a 20-byte hex address")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", token_in) or not re.fullmatch(
            r"0x[0-9a-fA-F]{40}", token_out
        ):
            raise ValueError("token addresses must be 20-byte hex addresses")
        if any(type(decimals) is not int or not 0 <= decimals <= 255 for decimals in (
            token_in_decimals, token_out_decimals
        )):
            raise ValueError("token decimals must be integers from 0 through 255")

        request = {
            "user_address": user_address.lower(),
            "chain_id": chain_id,
            "chain_run_id": chain_run_id.lower(),
            "principal_amount": principal_amount,
            "token_in": token_in.lower(),
            "token_out": token_out.lower(),
            "token_in_decimals": token_in_decimals,
            "token_out_decimals": token_out_decimals,
            "pool_key": pool_key,
            "input_snapshot": input_snapshot,
            "opportunity_id": opportunity_id,
        }
        key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
        request_hash = _canonical_hash(request)
        now = _utcnow()

        try:
            with self._sessions() as session, session.begin():
                existing_key = session.get(IdempotencyKey, key_hash)
                if existing_key is not None:
                    return self._resolve_idempotent_key(session, existing_key, request_hash)

                run_id = str(uuid4())
                run = Run(
                    id=run_id,
                    chain_run_id=chain_run_id.lower(),
                    user_address=user_address.lower(),
                    chain_id=chain_id,
                    state=RunState.CREATED.value,
                    principal_amount=Decimal(principal_amount),
                    token_in=token_in.lower(),
                    token_out=token_out.lower(),
                    token_in_decimals=token_in_decimals,
                    token_out_decimals=token_out_decimals,
                    pool_key=pool_key,
                    input_snapshot=input_snapshot,
                    opportunity_id=opportunity_id,
                    state_evidence={"source": "api_request", "persisted_before_side_effect": True},
                    created_at=now,
                    updated_at=now,
                )
                session.add(run)
                session.add(
                    RunTransition(
                        run_id=run_id,
                        before_state="NONE",
                        after_state=RunState.CREATED.value,
                        actor=user_address.lower(),
                        reason="RUN_CREATED",
                        evidence={"opportunity_id": opportunity_id},
                        created_at=now,
                    )
                )
                session.add(
                    IdempotencyKey(
                        key_hash=key_hash,
                        operation="create_run",
                        request_hash=request_hash,
                        resource_id=run_id,
                        response={"run_id": run_id, "state": RunState.CREATED.value},
                        created_at=now,
                    )
                )
                session.flush()
                return run
        except IntegrityError as exc:
            # Two identical requests can race on the unique idempotency key. Re-read
            # only after the failed transaction has rolled back, then resolve safely.
            with self._sessions() as session:
                existing_key = session.get(IdempotencyKey, key_hash)
                if existing_key is not None:
                    return self._resolve_idempotent_key(session, existing_key, request_hash)
                existing_run = session.scalar(select(Run).where(Run.chain_run_id == chain_run_id.lower()))
                if existing_run is not None:
                    raise IdempotencyConflict("chain_run_id is already assigned to another run") from exc
            raise

    @staticmethod
    def _resolve_idempotent_key(
        session: Session, existing_key: IdempotencyKey, request_hash: str
    ) -> Run:
        if existing_key.operation != "create_run" or existing_key.request_hash != request_hash:
            raise IdempotencyConflict("idempotency key was already used for a different request")
        existing_run = session.get(Run, existing_key.resource_id)
        if existing_run is None:
            raise RuntimeError("idempotency record points to a missing run")
        return existing_run

    def transition(
        self,
        run_id: str,
        new_state: RunState,
        *,
        actor: str,
        reason: str,
        evidence: dict[str, object],
        fields: dict[str, object] | None = None,
    ) -> Run:
        if not isinstance(new_state, RunState):
            raise TypeError("new_state must be a RunState")
        if not actor or len(actor) > 128 or not reason or len(reason) > 80:
            raise ValueError("actor and reason are required and must fit the audit schema")
        if not isinstance(evidence, dict):
            raise TypeError("transition evidence must be a JSON object")
        _validate_json(evidence)
        _validate_json(fields or {})
        now = _utcnow()
        with self._sessions() as session, session.begin():
            run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            current = RunState(run.state)
            if new_state not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(f"{current.value} -> {new_state.value} is not allowed")
            before_state = current.value
            run.state = new_state.value
            run.state_reason = reason
            run.state_evidence = evidence
            run.updated_at = now
            for field, value in (fields or {}).items():
                if field not in {
                    "acquired_amount",
                    "estimated_net_profit",
                    "simulated_proceeds",
                    "principal_recovered",
                    "shortfall",
                    "credited_amount",
                }:
                    raise ValueError(f"field {field!r} cannot be updated by a transition")
                if value is not None and type(value) is not int:
                    raise ValueError(f"{field} must be an integer base-unit amount")
                if value is not None and value < 0 and field != "estimated_net_profit":
                    raise ValueError(f"{field} cannot be negative")
                setattr(run, field, None if value is None else Decimal(value))
            session.add(
                RunTransition(
                    run_id=run_id,
                    before_state=before_state,
                    after_state=new_state.value,
                    actor=actor,
                    reason=reason,
                    evidence=evidence,
                    created_at=now,
                )
            )
            session.flush()
            return run

    def get(self, run_id: str, *, user_address: str | None = None) -> Run | None:
        with self._sessions() as session:
            query = select(Run).where(Run.id == run_id)
            if user_address is not None:
                query = query.where(Run.user_address == user_address.lower())
            return session.scalar(query)
