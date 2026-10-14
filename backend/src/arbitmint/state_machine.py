from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc)


def _canonical_hash(value: Any) -> str:
    def reject_floats(item: Any) -> None:
        if isinstance(item, float):
            raise TypeError("floating-point values are forbidden in run inputs")
        if isinstance(item, dict):
            for child in item.values():
                reject_floats(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                reject_floats(child)

    reject_floats(value)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


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
        if not chain_run_id.startswith("0x") or len(chain_run_id) != 66:
            raise ValueError("chain_run_id must be a 32-byte hex value")

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

        with self._sessions() as session, session.begin():
            existing_key = session.get(IdempotencyKey, key_hash)
            if existing_key is not None:
                if existing_key.operation != "create_run" or existing_key.request_hash != request_hash:
                    raise IdempotencyConflict("idempotency key was already used for a different request")
                existing_run = session.get(Run, existing_key.resource_id)
                if existing_run is None:
                    raise RuntimeError("idempotency record points to a missing run")
                return existing_run

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
