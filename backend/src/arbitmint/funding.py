from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid5, NAMESPACE_URL

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.models import FundingRecord, Run
from arbitmint.state_machine import RunRepository, RunState


class FundingConfigurationError(RuntimeError):
    pass


class FundingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundingCapabilities:
    provider_name: str
    workflow_verified: bool
    supported_chain_ids: frozenset[int]
    supported_tokens: frozenset[str]
    supports_principal_return: bool
    supports_redemption: bool


@dataclass(frozen=True)
class ProviderRequest:
    reference: str
    status: str
    metadata: dict[str, object]


class SandboxFundingProvider(Protocol):
    capabilities: FundingCapabilities

    def request_funding(
        self, *, request_id: str, amount: int, token_address: str, chain_id: int
    ) -> ProviderRequest: ...

    def get_status(self, *, reference: str) -> ProviderRequest: ...

    def request_redemption(self, *, request_id: str, amount: int, token_address: str, chain_id: int) -> ProviderRequest: ...


class OnchainBalanceReader(Protocol):
    def balance_of(self, *, token_address: str, owner: str, chain_id: int) -> int: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FundingAdapter:
    """Provider-neutral sandbox adapter; no default provider is enabled."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        provider: SandboxFundingProvider,
        balance_reader: OnchainBalanceReader,
    ) -> None:
        self._sessions = sessions
        self._provider = provider
        self._balance_reader = balance_reader
        self._runs = RunRepository(sessions)

    def request_funding(self, run_id: str, *, amount: int, token_address: str) -> FundingRecord:
        run = self._get_run(run_id)
        self._validate(amount=amount, token_address=token_address, chain_id=run.chain_id, redeem=False)
        request_id = str(uuid5(NAMESPACE_URL, f"arbitmint:fund:{run_id}"))
        existing = self._find(run_id, "FUND")
        if existing is not None and existing.status not in {"CREATED", "PENDING", "FAILED"}:
            return existing
        if existing is None:
            now = _now()
            with self._sessions() as session, session.begin():
                record = FundingRecord(
                    run_id=run_id,
                    operation="FUND",
                    provider=self._provider.capabilities.provider_name,
                    request_id=request_id,
                    amount=amount,
                    currency=token_address.lower(),
                    status="CREATED",
                    response_metadata={"environment": "sandbox", "chain_id": run.chain_id},
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)

        try:
            response = self._provider.request_funding(
                request_id=request_id,
                amount=amount,
                token_address=token_address.lower(),
                chain_id=run.chain_id,
            )
        except TimeoutError:
            return self._update(run_id, "FUND", status="PENDING", sanitized_error="PROVIDER_TIMEOUT")
        except FundingProviderError:
            return self._update(run_id, "FUND", status="FAILED", sanitized_error="PROVIDER_ERROR")
        return self._update(
            run_id,
            "FUND",
            status=self._normalize_status(response.status),
            reference=response.reference,
            metadata=response.metadata,
        )

    def refresh_funding(self, run_id: str) -> FundingRecord:
        record = self._find(run_id, "FUND")
        if record is None or not record.provider_reference:
            raise FundingProviderError("funding request has no provider reference to reconcile")
        try:
            response = self._provider.get_status(reference=record.provider_reference)
        except TimeoutError:
            return self._update(run_id, "FUND", status="PENDING", sanitized_error="PROVIDER_TIMEOUT")
        return self._update(
            run_id,
            "FUND",
            status=self._normalize_status(response.status),
            reference=response.reference,
            metadata=response.metadata,
        )

    def confirm_funding(self, run_id: str, *, token_address: str) -> Run:
        record = self._find(run_id, "FUND")
        run = self._get_run(run_id)
        if record is None or record.status != "CONFIRMED" or not record.provider_reference:
            raise FundingProviderError("provider funding status is not confirmed")
        observed = self._balance_reader.balance_of(
            token_address=token_address.lower(), owner=run.user_address, chain_id=run.chain_id
        )
        required = int(run.principal_amount)
        if type(observed) is not int or observed < required:
            raise FundingProviderError("required on-chain token balance is not independently confirmed")
        return self._runs.transition(
            run_id,
            RunState.FUNDED,
            actor="funding_adapter",
            reason="SANDBOX_FUNDING_AND_ONCHAIN_BALANCE_CONFIRMED",
            evidence={
                "provider": record.provider,
                "provider_reference": record.provider_reference,
                "provider_status": record.status,
                "chain_id": run.chain_id,
                "token_address": token_address.lower(),
                "observed_onchain_balance": observed,
                "required_balance": required,
            },
        )

    def confirm_redemption(self, run_id: str, *, token_address: str) -> Run:
        record = self._find(run_id, "REDEEM")
        run = self._get_run(run_id)
        if run.state != RunState.SETTLED.value:
            raise FundingProviderError("redemption can only follow confirmed settlement")
        if record is None or record.status != "CONFIRMED" or not record.provider_reference:
            raise FundingProviderError("provider redemption status is not confirmed")
        return self._runs.transition(
            run_id,
            RunState.REDEEMED,
            actor="funding_adapter",
            reason="SANDBOX_REDEMPTION_CONFIRMED",
            evidence={
                "provider": record.provider,
                "provider_reference": record.provider_reference,
                "provider_status": record.status,
                "chain_id": run.chain_id,
                "token_address": token_address.lower(),
                "amount": int(record.amount),
            },
        )

    def request_redemption(self, run_id: str, *, amount: int, token_address: str) -> FundingRecord:
        run = self._get_run(run_id)
        self._validate(amount=amount, token_address=token_address, chain_id=run.chain_id, redeem=True)
        request_id = str(uuid5(NAMESPACE_URL, f"arbitmint:redeem:{run_id}"))
        existing = self._find(run_id, "REDEEM")
        if existing is not None and existing.status not in {"CREATED", "PENDING", "FAILED"}:
            return existing
        if existing is None:
            now = _now()
            with self._sessions() as session, session.begin():
                session.add(
                    FundingRecord(
                        run_id=run_id,
                        operation="REDEEM",
                        provider=self._provider.capabilities.provider_name,
                        request_id=request_id,
                        amount=amount,
                        currency=token_address.lower(),
                        status="CREATED",
                        response_metadata={"environment": "sandbox", "chain_id": run.chain_id},
                        created_at=now,
                        updated_at=now,
                    )
                )
        try:
            response = self._provider.request_redemption(
                request_id=request_id,
                amount=amount,
                token_address=token_address.lower(),
                chain_id=run.chain_id,
            )
        except TimeoutError:
            return self._update(run_id, "REDEEM", status="PENDING", sanitized_error="PROVIDER_TIMEOUT")
        except FundingProviderError:
            return self._update(run_id, "REDEEM", status="FAILED", sanitized_error="PROVIDER_ERROR")
        return self._update(
            run_id,
            "REDEEM",
            status=self._normalize_status(response.status),
            reference=response.reference,
            metadata=response.metadata,
        )

    def _validate(self, *, amount: int, token_address: str, chain_id: int, redeem: bool) -> None:
        capabilities = self._provider.capabilities
        if chain_id != 1301:
            raise FundingConfigurationError("funding is restricted to Unichain Sepolia")
        if not capabilities.workflow_verified:
            raise FundingConfigurationError("sandbox provider lifecycle has not passed the required verification gate")
        if chain_id not in capabilities.supported_chain_ids:
            raise FundingConfigurationError("provider does not support the configured testnet")
        if token_address.lower() not in {item.lower() for item in capabilities.supported_tokens}:
            raise FundingConfigurationError("provider does not support the configured token")
        if redeem and not (capabilities.supports_principal_return and capabilities.supports_redemption):
            raise FundingConfigurationError("provider return and redemption semantics are not verified")
        if type(amount) is not int or amount <= 0:
            raise ValueError("amount must be a positive integer in base units")

    def _get_run(self, run_id: str) -> Run:
        with self._sessions() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise KeyError(run_id)
            return run

    def _find(self, run_id: str, operation: str) -> FundingRecord | None:
        with self._sessions() as session:
            return session.scalar(
                select(FundingRecord).where(
                    FundingRecord.run_id == run_id, FundingRecord.operation == operation
                )
            )

    def _update(
        self,
        run_id: str,
        operation: str,
        *,
        status: str,
        reference: str | None = None,
        metadata: dict[str, object] | None = None,
        sanitized_error: str | None = None,
    ) -> FundingRecord:
        with self._sessions() as session, session.begin():
            record = session.scalar(
                select(FundingRecord)
                .where(FundingRecord.run_id == run_id, FundingRecord.operation == operation)
                .with_for_update()
            )
            if record is None:
                raise RuntimeError("funding intent disappeared")
            record.status = status
            record.updated_at = _now()
            if reference is not None:
                record.provider_reference = reference
            if metadata is not None:
                record.response_metadata = _sanitize_metadata(metadata)
            record.sanitized_error = sanitized_error
            session.flush()
            return record

    @staticmethod
    def _normalize_status(status: str) -> str:
        normalized = status.upper()
        if normalized not in {"PENDING", "CONFIRMED", "FAILED"}:
            raise FundingProviderError("provider returned an unsupported status")
        return normalized


def _sanitize_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe_keys = {"status_code", "reason_code", "sandbox", "chain_id", "currency", "amount"}
    result: dict[str, object] = {}
    for key, value in metadata.items():
        normalized = key.lower()
        if normalized in safe_keys and isinstance(value, (str, int, bool)):
            result[normalized] = value
    return result
