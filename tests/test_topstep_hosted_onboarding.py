import asyncio

import pytest

from app.providers.base import ProviderCapabilityError, ProviderError
from app.providers.topstepx import TopStepXAdapter


class Response:
    def __init__(self, payload, *, status=200):
        self.payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http failure")

    def json(self):
        return self.payload


def test_login_and_account_search_return_only_safe_metadata(monkeypatch):
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        if url.endswith("/api/Auth/loginKey"):
            return Response({"success": True, "errorCode": 0, "token": "session-secret"})
        return Response({
            "success": True,
            "errorCode": 0,
            "accounts": [{
                "id": 123,
                "name": "display-label",
                "balance": 50000,
                "canTrade": True,
                "isVisible": True,
                "unexpectedSecret": "must-not-return",
            }],
        })

    monkeypatch.setattr("app.providers.topstepx.requests.post", post)
    adapter = TopStepXAdapter({"userName": "platform-user", "apiKey": "user-api-secret"})
    accounts = asyncio.run(adapter.list_accounts())
    assert accounts == [{
        "id": 123,
        "name": "display-label",
        "balance": 50000,
        "canTrade": True,
        "isVisible": True,
    }]
    assert calls[0][2] == {"userName": "platform-user", "apiKey": "user-api-secret"}
    assert calls[1][2] == {"onlyActiveAccounts": True}
    assert calls[1][1]["Authorization"] == "Bearer session-secret"


def test_provider_authentication_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(
        "app.providers.topstepx.requests.post",
        lambda *args, **kwargs: Response({
            "success": False,
            "errorCode": 3,
            "errorMessage": "upstream echoed user-api-secret",
            "token": None,
        }),
    )
    adapter = TopStepXAdapter({"userName": "platform-user", "apiKey": "user-api-secret"})
    with pytest.raises(ProviderError) as error:
        adapter._get_session_token()
    assert error.value.code == "auth_failed"
    assert "user-api-secret" not in str(error.value)


def test_session_validation_requires_success_and_new_token(monkeypatch):
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return Response({"success": True, "errorCode": 0, "newToken": "rotated-secret"})

    monkeypatch.setattr("app.providers.topstepx.requests.post", post)
    adapter = TopStepXAdapter({})
    token, expires_at = adapter.validate_session("old-secret")
    assert token == "rotated-secret" and expires_at is not None
    assert calls[0][0].endswith("/api/Auth/validate")
    assert calls[0][1]["Authorization"] == "Bearer old-secret"

    monkeypatch.setattr(
        "app.providers.topstepx.requests.post",
        lambda *args, **kwargs: Response({"success": True, "errorCode": 0}),
    )
    with pytest.raises(ProviderError) as error:
        adapter.validate_session("old-secret")
    assert error.value.code == "auth_invalid_session"
    assert "old-secret" not in str(error.value)


def test_account_selection_requires_exact_approved_id(monkeypatch):
    adapter = TopStepXAdapter(
        {"userName": "platform-user", "apiKey": "user-api-secret"},
        {"approvedAccountId": 456},
    )

    async def accounts():
        return [{"id": 123, "name": "first"}, {"id": 456, "name": "approved"}]

    monkeypatch.setattr(adapter, "list_accounts", accounts)
    with pytest.raises(ProviderCapabilityError, match="durable tenant approval"):
        asyncio.run(adapter.get_account())


def test_account_name_does_not_authorize_combine(monkeypatch):
    adapter = TopStepXAdapter(
        {"userName": "platform-user", "apiKey": "user-api-secret"},
        {"approvedAccountId": None},
    )

    async def accounts():
        return [{"id": 123, "name": "TRADING COMBINE 50K"}]

    monkeypatch.setattr(adapter, "list_accounts", accounts)
    with pytest.raises(ProviderCapabilityError):
        asyncio.run(adapter.get_account())
