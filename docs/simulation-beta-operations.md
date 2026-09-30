# Invite-only simulation beta operations

Release status: **not approved**. These settings require owner values before production admission.

The beta is local simulation only. It is not broker paper trading, brokerage execution, or evidence of future returns. Broker credential collection and live controls remain unavailable.

Required owner configuration:

- maximum active cohort and eligibility rules;
- named support owner, staffed hours, and escalation contact;
- approved privacy, retention, deletion, incident, and acceptable-use policies;
- incident thresholds, suspension authority, recovery objectives, rollback authority;
- physical TPM provisioning, offline recovery custody, deployment topology, backup separation, and key custodians.

Minimum operational behavior:

- Critical: suspected cross-tenant disclosure, secret exposure, duplicate execution, kill-switch failure, or deleted-data resurrection. Suspend admissions and new runs immediately.
- High: durable ownership/recovery failure or prolonged database/market-data degradation. Block new runs and show degraded status.
- Maintenance must block new starts before rollout; rollback is triggered by a critical event, failed migration/recovery check, or warning/security gate regression.
- Invite revocation blocks new runs but retains safe logout, export, deletion, and support access.
- Evidence must record revision, commands, statuses, durations, counts, environment, and hashes. Host-level checks may not be called passed without repository-host evidence.

## Required protected-branch checks

Require pull requests, current approval after the latest push, conversation resolution, no force pushes, and these checks:

`backend-tests`, `security-and-tenant`, `durable-recovery`, `fresh-postgres-migration`, `locked-python-install`, `python-audit`, `warning-budget`, `frontend-test-build-audit`, `demo-smoke`, `openspec-strict`, `secret-scan`, and `release-evidence`.

Retain test, audit, migration, drill, warning, and evidence artifacts for the owner-approved period. This file defines desired host settings; it is not evidence that they are enabled.

## Durable simulation worker

Control and market-input HTTP requests only persist commands or deterministic
simulation input. They never own evaluation. The database-backed worker:

- acquires and renews a fenced lease;
- validates kill, reconciliation, strategy/configuration, schedule, and freshness;
- commits evaluation and modeled economic effects atomically; and
- recovers only after checkpoint and financial-state reconciliation.

Run the PostgreSQL process-restart drill only against a disposable database
whose name contains `test` or `drill`:

```powershell
$env:DURABLE_RESTART_DRILL_DATABASE_URL = "postgresql://.../durable_restart_test"
.\venv\Scripts\python.exe scripts\durable_simulation_restart_drill.py `
  --output-dir artifacts\durable-restart-drill
```

The drill intentionally terminates a child worker with exit code 91. A PASS
requires a higher takeover fence, no duplicate evaluation/order/fill/fee/ledger
or risk effect, and a killed run which remains terminal after replacement.
