from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from arbitmint.db import Base, make_engine
from arbitmint.funding import (
    FundingAdapter,
    FundingCapabilities,
    FundingConfigurationError,
    ProviderRequest,
)
from arbitmint.models import FundingRecord, Run
from arbitmint.state_machine import RunRepository, RunState


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def create_run(sessions: sessionmaker[Session]) -> str:
    return RunRepository(sessions).create(
        idempotency_key="fund-test",
        user_address="0x" + "11" * 20,
        chain_id=1301,
        chain_run_id="0x" + "01" * 32,
        principal_amount=1_000_000,
        token_in="0x" + "22" * 20,
        token_out="0x" + "33" * 20,
        token_in_decimals=6,
        token_out_decimals=18,
        pool_key={},
        input_snapshot={},
    ).id


class Provider:
    def __init__(self, sessions: sessionmaker[Session], *, verified: bool) -> None:
        self.capabilities = FundingCapabilities(
            provider_name="test-sandbox",
            workflow_verified=verified,
            supported_chain_ids=frozenset({1301}),
            supported_tokens=frozenset({"0x" + "22" * 20}),
            supports_principal_return=False,
            supports_redemption=False,
        )
        self.sessions = sessions
        self.requested = False

    def request_funding(self, *, request_id: str, amount: int, token_address: str, chain_id: int) -> ProviderRequest:
        with self.sessions() as session:
            record = session.query(FundingRecord).one()
            assert record.status == "CREATED"
        self.requested = True
        return ProviderRequest("sandbox-ref", "CONFIRMED", {"status_code": 200, "authorization": "secret"})

    def get_status(self, *, reference: str) -> ProviderRequest:
        return ProviderRequest(reference, "CONFIRMED", {})

    def request_redemption(self, **kwargs: object) -> ProviderRequest:
        raise AssertionError("redemption should not be attempted")


class BalanceReader:
    def balance_of(self, *, token_address: str, owner: str, chain_id: int) -> int:
        return 1_000_000


def test_funding_intent_is_durable_before_provider_call_and_balance_gated(
    sessions: sessionmaker[Session],
) -> None:
    run_id = create_run(sessions)
    provider = Provider(sessions, verified=True)
    adapter = FundingAdapter(sessions, provider, BalanceReader())

    record = adapter.request_funding(run_id, amount=1_000_000, token_address="0x" + "22" * 20)

    assert provider.requested is True
    assert record.status == "CONFIRMED"
    assert record.response_metadata == {"status_code": 200}
    funded = adapter.confirm_funding(run_id, token_address="0x" + "22" * 20)
    assert funded.state == RunState.FUNDED.value


def test_unverified_funding_provider_is_blocked_before_side_effect(
    sessions: sessionmaker[Session],
) -> None:
    run_id = create_run(sessions)
    provider = Provider(sessions, verified=False)
    adapter = FundingAdapter(sessions, provider, BalanceReader())

    with pytest.raises(FundingConfigurationError, match="verification gate"):
        adapter.request_funding(run_id, amount=1_000_000, token_address="0x" + "22" * 20)
    assert provider.requested is False
    with sessions() as session:
        assert session.query(FundingRecord).count() == 0


def test_wrong_chain_and_token_are_rejected(sessions: sessionmaker[Session]) -> None:
    run_id = create_run(sessions)
    provider = Provider(sessions, verified=True)
    adapter = FundingAdapter(sessions, provider, BalanceReader())
    with sessions() as session, session.begin():
        run = session.get(Run, run_id)
        assert run is not None
        run.chain_id = 130
    with pytest.raises(FundingConfigurationError, match="Sepolia"):
        adapter.request_funding(run_id, amount=1, token_address="0x" + "22" * 20)
