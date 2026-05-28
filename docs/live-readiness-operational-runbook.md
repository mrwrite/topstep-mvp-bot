# Live-Readiness Operational Runbook

Live trading is disabled by design. Do not change this during demos or incident response. A passing launch gate is evidence collection only until a separate live-enablement change is reviewed, tested, and approved.

## Immediate Containment

1. Confirm `/health/live` reports `live_trading_enabled: false`.
2. Confirm `/ops/status` reports `execution_mode: paper-only`.
3. Keep `ENABLE_LIVE_TRADING=false` and `ALLOW_CREATE_ALL=false` in hosted environments.
4. If any user reports unexpected automation, activate `/risk/kill-switches` for the user/account/integration scope.
5. Stop bot sessions from the dashboard or `POST /scheduler/stop-bot`.

## Readiness Diagnostics

- Use `/launch-gate?integration_id=<id>&account_id=<account>&symbol=<symbol>` for the scoped blocker list.
- Use `/risk/settings` and `/risk/decisions` for risk policy and order-block reasons.
- Use `/risk/kill-switches?active_only=true` for active stop records.
- Use `/scheduler/paper-accounts`, `/scheduler/paper-ledger`, `/scheduler/open-orders`, and `/scheduler/positions` for paper account state.
- Use `/reconciliation/runs`, `/reconciliation/runs/{id}/events`, and `/reconciliation/retry-decisions` for provider mismatch and retry diagnostics.
- Use `/health/ready` to verify database, config, migration, and live-disabled status.

## Reconciliation Incident

1. Do not retry a live order. Live execution should remain unreachable.
2. Preserve request id, user id, integration id, account id, symbol, provider order id, and client order id.
3. Inspect reconciliation runs and events for normalized status, mismatches, and account locks.
4. Keep the reconciliation lock active until provider state is known.
5. Contact the user with paper/live-disabled language and the current blocker reason.

## Migration Incident

1. Treat a failing production migration check as a launch blocker.
2. Do not rely on runtime `create_all()` in production.
3. Run `alembic current` and `alembic heads` against the hosted database.
4. Back up the database before applying `alembic upgrade head`.
5. Verify `/health/ready` returns HTTP 200 after migration.

## Support Redaction

Never paste API keys, secrets, refresh tokens, raw credentials, or full provider payloads into support notes. Use request ids, order ids, account ids, integration ids, and redacted diagnostic payloads.

## Demo Checklist

- Live disabled banner is visible.
- Readiness checklist shows all blockers.
- Emergency stop is keyboard reachable.
- Paper ledger and paper orders are visible.
- Launch gate still reports `live_trading_available: false`.
- Investor walkthrough notes that paper results are simulations and do not guarantee live performance.
