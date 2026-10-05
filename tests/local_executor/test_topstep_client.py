from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from local_executor.credentials import TopstepCredentials
from local_executor.journal import LocalJournal
from local_executor.rate_budget import (
    LOCAL_RATE_BUDGETS,
    DurableRateLimiter,
    LocalRateLimitError,
)
from local_executor.topstep_client import LocalProviderError, LocalTopstepClient


class FakeResponse:
    def __init__(self, body, *, status=200, headers=None):
        self._body = body
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def success(**fields):
    return FakeResponse({"success": True, "errorCode": 0, **fields})


@pytest.fixture()
def journal(tmp_path):
    value = LocalJournal.open(tmp_path / "client.db", secure_permissions=False)
    yield value
    value.close()


def client(journal, http, *, clock=None, retries=0):
    limiter = DurableRateLimiter(journal.session_factory, clock=clock)
    return LocalTopstepClient(limiter, http_session=http, sleep=lambda _seconds: None,
                              read_retries=retries)


def test_authentication_and_validation_return_memory_session_tokens(journal):
    http = FakeHttp(success(token="session-one"), success(newToken="session-two"))
    api = client(journal, http)
    credentials = TopstepCredentials(username="tester", api_key="dedicated-key")
    first = api.authenticate(credentials)
    second = api.validate_session(first.value)
    assert first.value == "session-one" and second.value == "session-two"
    assert http.calls[0][1]["json"] == {"userName": "tester", "apiKey": "dedicated-key"}
    assert http.calls[1][1]["headers"]["Authorization"] == "Bearer session-one"
    assert http.calls[1][1]["json"] == {}


@pytest.mark.parametrize("body", [ValueError("bad json"), [], {"success": True, "errorCode": 0}])
def test_authentication_rejects_malformed_responses_without_leaking_credentials(journal, body):
    http = FakeHttp(FakeResponse(body))
    api = client(journal, http)
    with pytest.raises(LocalProviderError) as exc_info:
        api.authenticate(TopstepCredentials(username="tester", api_key="secret-fixture"))
    assert "secret-fixture" not in str(exc_info.value)
    assert "secret-fixture" not in str(exc_info.value.to_dict())


def test_provider_rejection_uses_typed_redacted_error(journal):
    http = FakeHttp(FakeResponse({
        "success": False, "errorCode": 3,
        "errorMessage": "credential secret-fixture rejected",
    }))
    api = client(journal, http)
    with pytest.raises(LocalProviderError) as exc_info:
        api.authenticate(TopstepCredentials(username="tester", api_key="secret-fixture"))
    assert exc_info.value.classification == "provider_rejected"
    assert exc_info.value.provider_error_code == 3
    assert "secret-fixture" not in str(exc_info.value.to_dict())


def test_exact_account_selection_never_substitutes_another_owned_account(journal):
    http = FakeHttp(
        success(accounts=[
            {"id": 101, "name": "do-not-classify", "canTrade": True, "isVisible": True},
            {"id": 202, "name": "also-ignore", "canTrade": True, "isVisible": True},
        ]),
        success(accounts=[
            {"id": 101, "name": "do-not-classify", "canTrade": True, "isVisible": True},
        ]),
    )
    api = client(journal, http)
    assert api.select_exact_account("token", 202).id == 202
    with pytest.raises(LocalProviderError, match="exact_account_not_found"):
        api.select_exact_account("token", 999)
    assert http.calls[0][1]["json"] == {"onlyActiveAccounts": True}


def test_live_contract_and_history_requests_are_rejected_before_network(journal):
    http = FakeHttp()
    api = client(journal, http)
    now = datetime.now(timezone.utc)
    with pytest.raises(LocalProviderError, match="live_provider_path_prohibited"):
        api.search_contracts("token", "MES", live=True)
    with pytest.raises(LocalProviderError, match="live_provider_path_prohibited"):
        api.retrieve_bars(token="token", contract_id="contract", start=now - timedelta(minutes=1),
                          end=now, unit=2, unit_number=1, limit=10, live=True)
    assert http.calls == []


def test_contract_and_history_requests_always_send_simulated_selection(journal):
    http = FakeHttp(
        success(contracts=[{
            "id": "CON.F.US.MES.Z26", "name": "MESZ6", "symbolId": "F.US.MES",
            "tickSize": 0.25, "tickValue": 1.25, "activeContract": True,
        }]),
        success(bars=[{"t": "2026-10-02T12:00:00Z", "o": 1, "h": 2, "l": 1,
                       "c": 2, "v": 5}]),
    )
    api = client(journal, http)
    now = datetime.now(timezone.utc)
    assert api.search_contracts("token", "MES")[0].id == "CON.F.US.MES.Z26"
    assert api.retrieve_bars(token="token", contract_id="CON.F.US.MES.Z26",
                             start=now - timedelta(minutes=1), end=now,
                             unit=2, unit_number=1, limit=10)[0].volume == 5
    assert http.calls[0][1]["json"]["live"] is False
    assert http.calls[1][1]["json"]["live"] is False
    assert http.calls[1][1]["json"]["includePartialBar"] is False


def test_order_trade_position_searches_are_normalized_and_windowed(journal):
    order = {
        "id": 11, "accountId": 7, "contractId": "contract", "creationTimestamp": "time",
        "status": 1, "type": 2, "side": 0, "size": 1, "customTag": "tag",
    }
    trade = {
        "id": 12, "accountId": 7, "orderId": 11, "contractId": "contract",
        "creationTimestamp": "time", "side": 0, "size": 1, "price": 5000.25,
        "profitAndLoss": None, "voided": False,
    }
    position = {
        "id": 13, "accountId": 7, "contractId": "contract", "creationTimestamp": "time",
        "type": 1, "size": 1, "averagePrice": 5000.25,
    }
    http = FakeHttp(success(orders=[order]), success(orders=[order]),
                    success(trades=[trade]), success(positions=[position]))
    api = client(journal, http)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, tzinfo=timezone.utc)
    assert api.search_orders("token", account_id=7, start=start, end=end)[0].custom_tag == "tag"
    assert api.search_open_orders("token", account_id=7)[0].size == 1
    assert api.search_trades("token", account_id=7, start=start, end=end)[0].price == "5000.25"
    assert api.search_open_positions("token", account_id=7)[0].average_price == "5000.25"
    assert http.calls[0][1]["json"] == {
        "accountId": 7,
        "startTimestamp": start.isoformat(),
        "endTimestamp": end.isoformat(),
    }
    with pytest.raises(ValueError, match="invalid_search_window"):
        api.search_orders("token", account_id=7, start=end, end=start)


def test_read_transport_and_server_errors_have_bounded_retry(journal):
    http = FakeHttp(requests.ConnectionError("secret should not escape"),
                    FakeResponse({}, status=503), success(accounts=[]))
    api = client(journal, http, retries=2)
    assert api.search_active_accounts("token") == ()
    assert len(http.calls) == 3


def test_provider_429_creates_durable_cooldown(journal):
    now = [datetime(2026, 10, 2, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    http = FakeHttp(FakeResponse({}, status=429, headers={"Retry-After": "40"}))
    api = client(journal, http, clock=clock)
    with pytest.raises(LocalProviderError, match="provider_rate_limited"):
        api.search_active_accounts("token")

    replacement = client(journal, FakeHttp(success(accounts=[])), clock=clock)
    with pytest.raises(LocalRateLimitError, match="provider_rate_cooldown"):
        replacement.search_active_accounts("token")
    now[0] += timedelta(seconds=41)
    assert replacement.search_active_accounts("token") == ()


def test_local_rate_budgets_are_below_documented_provider_limits(journal):
    assert LOCAL_RATE_BUDGETS["history"].limit < 50
    assert LOCAL_RATE_BUDGETS["history"].window_seconds == 30
    assert LOCAL_RATE_BUDGETS["general"].limit < 200
    assert LOCAL_RATE_BUDGETS["general"].window_seconds == 60
    limiter = DurableRateLimiter(journal.session_factory,
                                 clock=lambda: datetime(2026, 10, 2, tzinfo=timezone.utc))
    for _ in range(LOCAL_RATE_BUDGETS["history"].limit):
        limiter.acquire("history")
    with pytest.raises(LocalRateLimitError, match="local_rate_budget_exhausted"):
        limiter.acquire("history")
