from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.authorization import TenantContext
from app.durable_simulation import WorkerSettings, process_run, submit_command, submit_start
from app.simulation_evaluation import process_market_input, queue_market_input
from app.time_utils import utc_now


CRASH_EXIT = 91
SETTINGS = WorkerSettings(lease_seconds=6, renewal_seconds=2)


def _bars(event_at):
    prices = list(range(140, 90, -1))
    return [
        {
            "timestamp": (event_at - timedelta(minutes=len(prices) - index - 1)).isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1,
        }
        for index, price in enumerate(prices)
    ]


def _session(database_url):
    engine = create_engine(database_url, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine)


def _worker(
    database_url: str,
    market_id: str,
    *,
    crash_after_checkpoint: bool,
    worker_id: str | None = None,
) -> int:
    _, Session = _session(database_url)
    db = Session()
    worker_id = worker_id or f"restart-drill-worker:{uuid4().hex}"
    try:
        market = db.get(models.SimulationMarketInput, market_id)
        if market is None:
            return 4
        user = db.get(models.User, market.user_id)
        tenant = TenantContext(user.id, user.username)
        run = process_run(db, tenant, market.run_id, worker_id, SETTINGS)
        if run.state == "killed":
            db.commit()
            return 0
        lease = db.get(models.SimulationLease, run.id)

        def inject(stage):
            if crash_after_checkpoint and stage == "after_checkpoint":
                os._exit(CRASH_EXIT)

        process_market_input(
            db,
            tenant,
            run.id,
            market.id,
            owner_id=worker_id,
            fence=lease.fencing_token,
            now=utc_now(),
            inject=inject,
        )
        db.commit()
        return 0
    finally:
        db.close()


def _spawn(
    database_url: str,
    market_id: str,
    crash: bool,
    *,
    worker_id: str | None = None,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--database-url",
        database_url,
        "--market-id",
        market_id,
    ]
    if crash:
        command.append("--crash-after-checkpoint")
    if worker_id:
        command.extend(["--worker-id", worker_id])
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _counts(db, run_id):
    return {
        "evaluations": db.query(models.SimulationEvaluation).filter_by(run_id=run_id).count(),
        "orders": db.query(models.PaperOrder).filter_by(simulation_run_id=run_id).count(),
        "fills": db.query(models.PaperFill).filter_by(simulation_run_id=run_id).count(),
        "ledger_entries": db.query(models.PaperLedgerEntry).filter_by(simulation_run_id=run_id).count(),
        "risk_trade_count": (
            db.get(models.SimulationRiskCounter, run_id).trade_count
            if db.get(models.SimulationRiskCounter, run_id) else 0
        ),
    }


def _write_reports(report, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "durable-simulation-restart-drill.json"
    markdown_path = output_dir / "durable-simulation-restart-drill.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Durable simulation process-restart drill",
        "",
        f"- Result: **{report['result']}**",
        f"- Lease takeover fence advanced: `{report['lease_takeover']['fence_advanced']}`",
        f"- Crash process exit: `{report['crash']['exit_code']}`",
        f"- Economic counts after recovery: `{json.dumps(report['recovered_counts'], sort_keys=True)}`",
        f"- Killed run remained killed: `{report['kill_restart']['remained_killed']}`",
        f"- Killed run effects: `{json.dumps(report['kill_restart']['counts'], sort_keys=True)}`",
        "",
        "This drill uses local simulation only. It does not contact a broker or demonstrate future returns.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def run_drill(database_url: str, output_dir: Path) -> int:
    database_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0].lower()
    if "test" not in database_name and "drill" not in database_name:
        raise RuntimeError("Restart drill requires a disposable database whose name contains 'test' or 'drill'.")
    engine, Session = _session(database_url)
    models.Base.metadata.create_all(engine)
    db = Session()
    suffix = uuid4().hex
    try:
        user = models.User(
            username=f"restart-{suffix}",
            email=f"restart-{suffix}@test",
            hashed_password="x",
        )
        db.add(user)
        db.flush()
        tenant = TenantContext(user.id, user.username)
        run, _, _ = submit_start(
            db,
            tenant,
            symbol="ES",
            configuration={
                "environment": "simulation",
                "trading_mode": "paper",
                "account_id": f"RESTART-{suffix}",
                "integration_id": None,
                "auto_trade": True,
                "quantity": 1,
                "min_bars": 30,
                "max_staleness_seconds": 300,
            },
            idempotency_key=f"restart-start-{suffix}",
        )
        first_at = utc_now()
        first, _ = queue_market_input(
            db,
            tenant,
            run.id,
            source="restart-drill",
            timeframe="1m",
            event_at=first_at,
            provider_sequence="1",
            payload={"bars": _bars(first_at)},
        )
        db.commit()
        run_id = run.id
        user_id = user.id
        first_id = first.id
    finally:
        db.close()

    first_process = _spawn(database_url, first_id, False)
    if first_process.returncode != 0:
        raise RuntimeError(f"Initial worker failed: {first_process.stderr}")

    db = Session()
    try:
        first_lease = db.get(models.SimulationLease, run_id)
        first_fence = first_lease.fencing_token
        second_at = utc_now()
        second, _ = queue_market_input(
            db,
            TenantContext(user_id, f"restart-{suffix}"),
            run_id,
            source="restart-drill",
            timeframe="1m",
            event_at=second_at,
            provider_sequence="2",
            payload={"bars": _bars(second_at)},
        )
        db.commit()
        second_id = second.id
    finally:
        db.close()

    time.sleep(7)
    crashed = _spawn(database_url, second_id, True)
    recovered = _spawn(database_url, second_id, False)

    db = Session()
    try:
        recovered_run = db.get(models.SimulationRun, run_id)
        recovered_lease = db.get(models.SimulationLease, run_id)
        recovered_owner = recovered_lease.owner_id
    finally:
        db.close()
    duplicate = _spawn(database_url, second_id, False, worker_id=recovered_owner)

    db = Session()
    try:
        recovered_run = db.get(models.SimulationRun, run_id)
        recovered_lease = db.get(models.SimulationLease, run_id)
        recovered_counts = _counts(db, run_id)
        recovered_state = recovered_run.state
        recovered_fence = recovered_lease.fencing_token

        killed_run, _, _ = submit_start(
            db,
            TenantContext(user_id, f"restart-{suffix}"),
            symbol="NQ",
            configuration={
                "environment": "simulation",
                "trading_mode": "paper",
                "account_id": f"KILL-{suffix}",
                "integration_id": None,
                "auto_trade": True,
                "quantity": 1,
                "min_bars": 30,
            },
            idempotency_key=f"kill-start-{suffix}",
        )
        kill_at = utc_now()
        killed_market, _ = queue_market_input(
            db,
            TenantContext(user_id, f"restart-{suffix}"),
            killed_run.id,
            source="restart-drill",
            timeframe="1m",
            event_at=kill_at,
            provider_sequence="1",
            payload={"bars": _bars(kill_at)},
        )
        submit_command(
            db,
            TenantContext(user_id, f"restart-{suffix}"),
            killed_run.id,
            idempotency_key=f"kill-{suffix}",
            name="kill",
        )
        db.commit()
        killed_run_id, killed_market_id = killed_run.id, killed_market.id
    finally:
        db.close()

    killed_restart = _spawn(database_url, killed_market_id, False)
    db = Session()
    try:
        killed_state = db.get(models.SimulationRun, killed_run_id).state
        killed_counts = _counts(db, killed_run_id)
    finally:
        db.close()

    assertions = {
        "crash_exit_is_controlled": crashed.returncode == CRASH_EXIT,
        "recovery_process_succeeded": recovered.returncode == 0,
        "duplicate_process_succeeded": duplicate.returncode == 0,
        "lease_fence_advanced": recovered_fence > first_fence,
        "run_returned_running": recovered_state == "running",
        "two_inputs_have_two_evaluations": recovered_counts["evaluations"] == 2,
        "no_duplicate_orders": recovered_counts["orders"] == 2,
        "no_duplicate_fills": recovered_counts["fills"] == 2,
        "no_duplicate_ledger_entries": recovered_counts["ledger_entries"] == 2,
        "risk_count_matches_fills": recovered_counts["risk_trade_count"] == 2,
        "killed_restart_process_succeeded": killed_restart.returncode == 0,
        "killed_run_remained_killed": killed_state == "killed",
        "killed_run_has_no_effects": all(value == 0 for value in killed_counts.values()),
    }
    report = {
        "result": "PASS" if all(assertions.values()) else "FAIL",
        "assertions": assertions,
        "crash": {"exit_code": crashed.returncode},
        "lease_takeover": {
            "first_fence": first_fence,
            "recovered_fence": recovered_fence,
            "fence_advanced": recovered_fence > first_fence,
        },
        "recovered_counts": recovered_counts,
        "kill_restart": {
            "process_exit": killed_restart.returncode,
            "state": killed_state,
            "remained_killed": killed_state == "killed",
            "counts": killed_counts,
        },
    }
    json_path, markdown_path = _write_reports(report, output_dir)
    print(json.dumps({"result": report["result"], "json": str(json_path), "markdown": str(markdown_path)}))
    return 0 if report["result"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("DURABLE_RESTART_DRILL_DATABASE_URL"))
    parser.add_argument("--output-dir", default=".tmp/durable-restart-drill")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--market-id")
    parser.add_argument("--crash-after-checkpoint", action="store_true")
    parser.add_argument("--worker-id")
    args = parser.parse_args()
    if not args.database_url:
        raise RuntimeError("DURABLE_RESTART_DRILL_DATABASE_URL or --database-url is required.")
    if args.child:
        if not args.market_id:
            raise RuntimeError("--market-id is required for child mode.")
        return _worker(
            args.database_url,
            args.market_id,
            crash_after_checkpoint=args.crash_after_checkpoint,
            worker_id=args.worker_id,
        )
    return run_drill(args.database_url, Path(args.output_dir))


if __name__ == "__main__":
    raise SystemExit(main())
