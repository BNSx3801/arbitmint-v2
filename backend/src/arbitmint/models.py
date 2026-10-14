from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arbitmint.db import Base

Amount = Numeric(78, 0, asdecimal=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_user_created", "user_address", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chain_run_id: Mapped[str] = mapped_column(String(66), unique=True, nullable=False)
    user_address: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    principal_amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    token_in: Mapped[str] = mapped_column(String(42), nullable=False)
    token_out: Mapped[str] = mapped_column(String(42), nullable=False)
    token_in_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    token_out_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_key: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    opportunity_id: Mapped[str | None] = mapped_column(String(64))
    amount_in: Mapped[Decimal | None] = mapped_column(Amount)
    acquired_amount: Mapped[Decimal | None] = mapped_column(Amount)
    estimated_net_profit: Mapped[Decimal | None] = mapped_column(Amount)
    simulated_proceeds: Mapped[Decimal | None] = mapped_column(Amount)
    principal_recovered: Mapped[Decimal | None] = mapped_column(Amount)
    shortfall: Mapped[Decimal | None] = mapped_column(Amount)
    credited_amount: Mapped[Decimal | None] = mapped_column(Amount)
    state_reason: Mapped[str | None] = mapped_column(String(80))
    state_evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transitions: Mapped[list[RunTransition]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunTransition(Base):
    __tablename__ = "run_transitions"
    __table_args__ = (Index("ix_run_transitions_run_time", "run_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    before_state: Mapped[str] = mapped_column(String(16), nullable=False)
    after_state: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run: Mapped[Run] = relationship(back_populates="transitions")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    response: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SideEffectIntent(Base):
    __tablename__ = "side_effect_intents"
    __table_args__ = (UniqueConstraint("run_id", "operation", name="uq_side_effect_run_operation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    reference: Mapped[str | None] = mapped_column(String(160))
    tx_hash: Mapped[str | None] = mapped_column(String(80))
    sanitized_error: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FundingRecord(Base):
    __tablename__ = "funding_records"
    __table_args__ = (UniqueConstraint("run_id", "operation", name="uq_funding_run_operation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    provider_reference: Mapped[str | None] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    currency: Mapped[str] = mapped_column(String(42), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    response_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    sanitized_error: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SimulatorRecord(Base):
    __tablename__ = "simulator_records"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    simulator_reference: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    sold_quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    unsold_quantity: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    gross_proceeds: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    fees: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    net_proceeds: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    captured_inputs: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChainEvent(Base):
    __tablename__ = "chain_events"
    __table_args__ = (
        UniqueConstraint("chain_id", "transaction_hash", "log_index", name="uq_chain_event_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    block_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ListenerCursor(Base):
    __tablename__ = "listener_cursors"

    chain_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_address: Mapped[str] = mapped_column(String(42), primary_key=True)
    next_block: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransactionRecord(Base):
    __tablename__ = "transaction_records"
    __table_args__ = (UniqueConstraint("chain_id", "transaction_hash", name="uq_tx_chain_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    receipt_block: Mapped[int | None] = mapped_column(BigInteger)
    confirmation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    sanitized_error: Mapped[str | None] = mapped_column(String(256))
