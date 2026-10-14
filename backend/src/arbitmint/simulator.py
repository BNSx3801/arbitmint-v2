from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from arbitmint.models import Run, SimulatorRecord
from arbitmint.state_machine import RunRepository, RunState


@dataclass(frozen=True)
class SimulatorConfig:
    price_numerator: int
    price_denominator: int
    max_quantity: int
    spread_bps: int = 0
    fee_bps: int = 0
    price_move_bps: int = 0
    latency_ms: int = 0
    failure_run_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        values = (
            self.price_numerator,
            self.price_denominator,
            self.max_quantity,
            self.spread_bps,
            self.fee_bps,
            self.price_move_bps,
            self.latency_ms,
        )
        if any(type(value) is not int for value in values):
            raise ValueError("simulator configuration must use integers")
        if self.price_numerator <= 0 or self.price_denominator <= 0 or self.max_quantity <= 0:
            raise ValueError("price ratio and depth must be positive")
        if not 0 <= self.spread_bps <= 10_000 or not 0 <= self.fee_bps <= 10_000:
            raise ValueError("spread and fee must be between 0 and 10,000 basis points")
        if not -9_999 <= self.price_move_bps <= 10_000 or self.latency_ms < 0:
            raise ValueError("invalid price movement or latency")


@dataclass(frozen=True)
class SimulationOutcome:
    run_id: str
    simulator_reference: str
    status: str
    input_quantity: int
    sold_quantity: int
    unsold_quantity: int
    gross_proceeds: int
    fees: int
    net_proceeds: int
    latency_ms: int
    configuration: dict[str, object]
    captured_inputs: dict[str, object]
    simulated: bool = True


class DeterministicVenueSimulator:
    def __init__(self, sessions: sessionmaker[Session], config: SimulatorConfig) -> None:
        config.validate()
        self._sessions = sessions
        self.config = config
        self._runs = RunRepository(sessions)

    def sell(self, run_id: str, *, quantity: int) -> SimulationOutcome:
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("quantity must be a positive integer in base units")
        with self._sessions() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.state not in {"EXECUTED", "STUCK"}:
                raise ValueError("simulated sale requires a confirmed execution")
            if run.acquired_amount is None or int(run.acquired_amount) != quantity:
                raise ValueError("simulator must use the confirmed acquired token quantity")

        configuration = asdict(self.config)
        configuration["failure_run_ids"] = list(self.config.failure_run_ids)
        captured = {
            "run_id": run_id,
            "quantity": quantity,
            "token_out": run.token_out,
            "token_out_decimals": run.token_out_decimals,
            "chain_id": run.chain_id,
        }
        ref_payload = json.dumps(
            {"config": configuration, "input": captured}, sort_keys=True, separators=(",", ":")
        ).encode()
        reference = "sim_" + hashlib.sha256(ref_payload).hexdigest()
        if run_id in self.config.failure_run_ids:
            outcome = SimulationOutcome(
                run_id=run_id,
                simulator_reference=reference,
                status="FAILED",
                input_quantity=quantity,
                sold_quantity=0,
                unsold_quantity=quantity,
                gross_proceeds=0,
                fees=0,
                net_proceeds=0,
                latency_ms=self.config.latency_ms,
                configuration=configuration,
                captured_inputs=captured,
            )
        else:
            sold = min(quantity, self.config.max_quantity)
            moved_num = self.config.price_numerator * (10_000 + self.config.price_move_bps)
            moved_den = self.config.price_denominator * 10_000
            gross = sold * moved_num // moved_den
            after_spread = gross * (10_000 - self.config.spread_bps) // 10_000
            fees = after_spread * self.config.fee_bps // 10_000
            net = after_spread - fees
            outcome = SimulationOutcome(
                run_id=run_id,
                simulator_reference=reference,
                status="PARTIAL" if sold < quantity else "SUCCESS",
                input_quantity=quantity,
                sold_quantity=sold,
                unsold_quantity=quantity - sold,
                gross_proceeds=gross,
                fees=fees,
                net_proceeds=net,
                latency_ms=self.config.latency_ms,
                configuration=configuration,
                captured_inputs=captured,
            )
        stored = self._persist(outcome)
        current = self._runs.get(run_id)
        target_state = RunState.STUCK if outcome.status == "FAILED" else RunState.SOLD
        if current is not None and current.state != target_state.value:
            self._runs.transition(
                run_id,
                target_state,
                actor="simulated_venue",
                reason="SIMULATOR_FAILED" if outcome.status == "FAILED" else "SIMULATOR_RESULT_RECORDED",
                evidence={
                    "simulated": True,
                    "simulator_reference": outcome.simulator_reference,
                    "sold_quantity": outcome.sold_quantity,
                    "unsold_quantity": outcome.unsold_quantity,
                    "net_proceeds": outcome.net_proceeds,
                },
                fields={"simulated_proceeds": outcome.net_proceeds},
            )
        return stored

    def _persist(self, outcome: SimulationOutcome) -> SimulationOutcome:
        with self._sessions() as session, session.begin():
            existing = session.get(SimulatorRecord, outcome.run_id)
            if existing is not None:
                if (
                    existing.simulator_reference != outcome.simulator_reference
                    or existing.captured_inputs != outcome.captured_inputs
                    or existing.configuration != outcome.configuration
                ):
                    raise ValueError("run already has a different immutable simulator result")
                return _to_outcome(existing)
            record = SimulatorRecord(
                run_id=outcome.run_id,
                simulator_reference=outcome.simulator_reference,
                status=outcome.status,
                input_quantity=Decimal(outcome.input_quantity),
                sold_quantity=Decimal(outcome.sold_quantity),
                unsold_quantity=Decimal(outcome.unsold_quantity),
                gross_proceeds=Decimal(outcome.gross_proceeds),
                fees=Decimal(outcome.fees),
                net_proceeds=Decimal(outcome.net_proceeds),
                latency_ms=outcome.latency_ms,
                configuration=outcome.configuration,
                captured_inputs=outcome.captured_inputs,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.flush()
            return outcome


def _to_outcome(record: SimulatorRecord) -> SimulationOutcome:
    return SimulationOutcome(
        run_id=record.run_id,
        simulator_reference=record.simulator_reference,
        status=record.status,
        input_quantity=int(record.input_quantity),
        sold_quantity=int(record.sold_quantity),
        unsold_quantity=int(record.unsold_quantity),
        gross_proceeds=int(record.gross_proceeds),
        fees=int(record.fees),
        net_proceeds=int(record.net_proceeds),
        latency_ms=record.latency_ms,
        configuration=record.configuration,
        captured_inputs=record.captured_inputs,
    )
