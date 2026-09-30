from cryptography.fernet import Fernet
from datetime import timedelta
from fastapi.testclient import TestClient
import pytest

from app import database, models
from app.main import app
from app.simulation_worker import recovery_cycle
from app.time_utils import utc_now

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset():
    models.Base.metadata.drop_all(database.engine)
    models.Base.metadata.create_all(database.engine)


def register_login(name):
    client.post("/auth/register", json={"username": name, "email": f"{name}@test", "password": "StrongPass1"})
    response = client.post("/auth/token", data={"username": name, "password": "StrongPass1"})
    return response.json()["access_token"]


def headers(token, key=None):
    value = {"Authorization": f"Bearer {token}", "X-Internal-Paper-Fixture": "true"}
    if key:
        value["Idempotency-Key"] = key
    return value


def integration(token):
    return client.post("/integrations", headers=headers(token), json={
        "display_name": "simulation fixture", "provider": "TOPSTEPX",
        "metadata": {"environment": "test"}, "credentials": {"userName": "fixture", "apiKey": "fixture"},
    }).json()


def start(token, provider, key="start-api"):
    return client.post("/scheduler/bot-sessions", headers=headers(token, key), json={
        "symbol": "ES", "trading_mode": "paper", "auto_trade": False,
        "integration_id": provider["id"], "account_id": "SIM",
    })


def test_api_controls_are_durable_idempotent_and_tenant_hidden():
    alice_token = register_login("api-alice")
    alice_integration = integration(alice_token)
    started = start(alice_token, alice_integration)
    assert started.status_code == 200
    run_id = started.json()["run_id"]
    assert started.json()["run_state"] == "starting"
    recovery_cycle(worker_id="api-test-worker")
    assert client.get(f"/simulation-runs/{run_id}", headers=headers(alice_token)).json()["state"] == "running"

    pause1 = client.post(f"/simulation-runs/{run_id}/commands/pause", headers=headers(alice_token, "pause-api"))
    pause2 = client.post(f"/simulation-runs/{run_id}/commands/pause", headers=headers(alice_token, "pause-api"))
    assert pause1.status_code == pause2.status_code == 202
    assert pause1.json()["command"]["id"] == pause2.json()["command"]["id"]
    assert pause2.json()["duplicate"] is True
    recovery_cycle(worker_id="api-test-worker")
    assert client.get(f"/simulation-runs/{run_id}", headers=headers(alice_token)).json()["state"] == "paused"

    bob_token = register_login("api-bob")
    assert client.get(f"/simulation-runs/{run_id}", headers=headers(bob_token)).status_code == 404
    assert client.post(
        f"/simulation-runs/{run_id}/commands/kill", headers=headers(bob_token, "cross-kill")
    ).status_code == 404


def test_risk_kill_durably_kills_run_and_survives_new_session():
    token = register_login("api-kill")
    provider = integration(token)
    run_id = start(token, provider, "start-kill").json()["run_id"]
    killed = client.post("/risk/kill-switches", headers=headers(token), json={
        "bot_session_id": run_id, "reason": "Emergency simulation stop",
    })
    assert killed.status_code == 200
    database.SessionLocal().close()
    status = client.get(f"/simulation-runs/{run_id}", headers=headers(token))
    assert status.json()["state"] == "killed"
    resume = client.post(
        f"/simulation-runs/{run_id}/commands/resume", headers=headers(token, "resume-after-kill")
    )
    assert resume.status_code == 202
    assert resume.json()["command"]["status"] == "failed"


def test_market_input_is_queued_then_processed_only_by_durable_worker():
    token = register_login("api-market")
    provider = integration(token)
    started = client.post("/scheduler/bot-sessions", headers=headers(token, "start-market"), json={
        "symbol": "ES",
        "trading_mode": "paper",
        "auto_trade": True,
        "integration_id": provider["id"],
        "account_id": "SIM-MARKET",
    })
    run_id = started.json()["run_id"]
    recovery_cycle(worker_id="api-market-worker")
    event_at = utc_now()
    prices = list(range(140, 90, -1))
    response = client.post(
        f"/simulation-runs/{run_id}/market-inputs",
        headers=headers(token),
        json={
            "source": "api-simulation-feed",
            "timeframe": "1m",
            "event_at": event_at.isoformat(),
            "provider_sequence": "1",
            "bars": [
                {
                    "timestamp": (
                        event_at - timedelta(minutes=len(prices) - index - 1)
                    ).isoformat(),
                    "close": price,
                }
                for index, price in enumerate(prices)
            ],
        },
    )
    assert response.status_code == 202
    assert response.json()["execution"] == "queued_for_durable_worker"
    db = database.SessionLocal()
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count() == 0
    db.close()
    recovery_cycle(worker_id="api-market-worker")
    status_response = client.get(f"/simulation-runs/{run_id}", headers=headers(token))
    status_payload = status_response.json()
    assert status_payload["data_freshness"] == "new"
    assert status_payload["last_evaluation_at"]
    assert status_payload["last_checkpoint_sequence"] == 1
    db = database.SessionLocal()
    assert db.query(models.SimulationEvaluation).filter_by(run_id=run_id).count() == 1
    assert db.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count() == 1
    assert db.query(models.PaperFill).filter_by(simulation_run_id=run_id).count() == 1
    db.close()


def test_all_run_controls_status_stream_and_market_queue_hide_cross_tenant_run():
    alice_token = register_login("matrix-alice")
    alice_integration = integration(alice_token)
    run_id = start(alice_token, alice_integration, "matrix-start").json()["run_id"]
    with database.SessionLocal() as db:
        command_count = db.query(models.SimulationCommand).filter_by(run_id=run_id).count()
        outbox_count = db.query(models.OutboxEvent).filter_by(aggregate_id=run_id).count()

    bob_token = register_login("matrix-bob")
    assert client.get(f"/simulation-runs/{run_id}", headers=headers(bob_token)).status_code == 404
    assert client.get(
        f"/simulation-runs/{run_id}/commands/not-a-command", headers=headers(bob_token)
    ).status_code == 404
    for command_name in ("pause", "resume", "stop", "kill"):
        response = client.post(
            f"/simulation-runs/{run_id}/commands/{command_name}",
            headers=headers(bob_token, f"cross-{command_name}"),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Simulation command rejected."
    market = client.post(
        f"/simulation-runs/{run_id}/market-inputs",
        headers=headers(bob_token),
        json={
            "source": "cross-tenant", "timeframe": "1m", "event_at": utc_now().isoformat(),
            "bars": [{"timestamp": utc_now().isoformat(), "close": 100}],
        },
    )
    assert market.status_code == 404
    assert client.get(
        f"/scheduler/run-bot?session_id={run_id}", headers=headers(bob_token)
    ).status_code == 404
    with database.SessionLocal() as db:
        assert db.query(models.SimulationCommand).filter_by(run_id=run_id).count() == command_count
        assert db.query(models.OutboxEvent).filter_by(aggregate_id=run_id).count() == outbox_count
        assert db.query(models.SimulationMarketInput).filter_by(run_id=run_id).count() == 0
