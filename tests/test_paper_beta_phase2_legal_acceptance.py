import os
from datetime import datetime, timedelta

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))

from app import database, models  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    yield


def register_user(username: str = "alice", email: str = "alice@example.com", password: str = "StrongPass1"):
    response = client.post("/auth/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201
    return response


def login_user(username: str = "alice", password: str = "StrongPass1") -> str:
    response = client.post(
        "/auth/token",
        data={"username": username, "password": password, "grant_type": "password"},
        headers={"user-agent": "pytest-browser legal-suite"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "user-agent": "pytest-browser legal-suite"}


def accept_all(token: str, metadata: dict | None = None):
    return client.post(
        "/legal/acceptances",
        headers=auth_headers(token),
        json={
            "accept_terms_of_service": True,
            "accept_privacy_policy": True,
            "accept_paper_trading_disclosure": True,
            "metadata": metadata or {"source": "pytest"},
        },
    )


def test_required_legal_documents_are_returned_with_versions_and_blockers():
    register_user()
    token = login_user()

    response = client.get("/legal/documents", headers=auth_headers(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["all_required_accepted"] is False
    assert payload["live_trading_enabled"] is False
    assert {document["document_type"] for document in payload["documents"]} == {
        "terms_of_service",
        "privacy_policy",
        "paper_trading_disclosure",
    }
    assert {document["version"] for document in payload["documents"]} == {
        "terms-v1",
        "privacy-v1",
        "paper-risk-v1",
    }
    assert {blocker["code"] for blocker in payload["blockers"]} == {
        "terms_acceptance_required",
        "privacy_acceptance_required",
        "paper_disclosure_required",
    }


def test_accepting_required_documents_records_audit_metadata_and_is_idempotent():
    register_user()
    token = login_user()

    accepted = accept_all(token, metadata={"source": "pytest", "api_token": "secret-token"})
    duplicate = accept_all(token)

    assert accepted.status_code == 200
    assert duplicate.status_code == 200
    assert accepted.json()["all_required_accepted"] is True
    assert duplicate.json()["all_required_accepted"] is True

    with database.SessionLocal() as db:
        records = db.query(models.LegalAcceptance).all()
        assert len(records) == 3
        assert all(record.user_agent_summary == "pytest-browser legal-suite" for record in records)
        assert all(record.ip_hash and record.ip_hash != "testclient" for record in records)
        assert all(record.acceptance_metadata["api_token"] == "[REDACTED]" for record in records)

    history = client.get("/legal/acceptances", headers=auth_headers(token))
    assert history.status_code == 200
    assert len(history.json()["acceptances"]) == 3


def test_acceptance_requires_explicit_confirmation_for_each_document():
    register_user()
    token = login_user()

    response = client.post(
        "/legal/acceptances",
        headers=auth_headers(token),
        json={
            "accept_terms_of_service": True,
            "accept_privacy_policy": True,
            "accept_paper_trading_disclosure": False,
        },
    )

    assert response.status_code == 400
    assert "paper_trading_disclosure" in response.json()["detail"]["missing_confirmations"]


def test_beta_access_check_blocks_until_current_legal_documents_are_accepted():
    register_user()
    token = login_user()

    blocked = client.get("/legal/beta-access-check", headers=auth_headers(token))
    assert blocked.status_code == 403
    assert blocked.headers["x-readiness-blocker"] in {
        "terms_acceptance_required",
        "privacy_acceptance_required",
        "paper_disclosure_required",
    }

    assert accept_all(token).status_code == 200
    allowed = client.get("/legal/beta-access-check", headers=auth_headers(token))
    assert allowed.status_code == 200
    assert allowed.json()["legal_acceptance_complete"] is True
    assert allowed.json()["live_trading_enabled"] is False


def test_reacceptance_is_required_when_document_version_changes():
    register_user()
    token = login_user()
    assert accept_all(token).status_code == 200

    with database.SessionLocal() as db:
        old_terms = db.query(models.LegalDocument).filter(models.LegalDocument.document_type == "terms_of_service").one()
        old_terms.active = 0
        db.add(
            models.LegalDocument(
                document_type="terms_of_service",
                version="terms-v2",
                title="Terms of Service",
                content_markdown="# Terms v2\n\nUpdated beta terms.",
                content_url="/legal/terms-v2",
                required=1,
                active=1,
                effective_at=datetime.utcnow() + timedelta(minutes=1),
            )
        )
        db.commit()

    status_response = client.get("/legal/documents", headers=auth_headers(token))
    status_payload = status_response.json()
    assert status_payload["all_required_accepted"] is False
    assert [blocker["code"] for blocker in status_payload["blockers"]] == ["terms_acceptance_required"]
    assert next(document for document in status_payload["documents"] if document["document_type"] == "terms_of_service")["version"] == "terms-v2"

    assert accept_all(token).status_code == 200
    final_status = client.get("/legal/documents", headers=auth_headers(token)).json()
    assert final_status["all_required_accepted"] is True

    history = client.get("/legal/acceptances", headers=auth_headers(token)).json()["acceptances"]
    assert {record["version"] for record in history if record["document_type"] == "terms_of_service"} == {
        "terms-v1",
        "terms-v2",
    }


def test_acceptance_history_is_user_scoped_and_live_trading_remains_blocked():
    register_user("alice", "alice@example.com", "StrongPass1")
    register_user("bob", "bob@example.com", "StrongPass1")
    alice_token = login_user("alice", "StrongPass1")
    bob_token = login_user("bob", "StrongPass1")

    assert accept_all(alice_token).status_code == 200

    alice_history = client.get("/legal/acceptances", headers=auth_headers(alice_token))
    bob_history = client.get("/legal/acceptances", headers=auth_headers(bob_token))
    bob_status = client.get("/legal/documents", headers=auth_headers(bob_token))

    assert len(alice_history.json()["acceptances"]) == 3
    assert bob_history.json()["acceptances"] == []
    assert bob_status.json()["all_required_accepted"] is False
    assert "paper_disclosure_required" in {blocker["code"] for blocker in bob_status.json()["blockers"]}

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["live_trading_enabled"] is False
