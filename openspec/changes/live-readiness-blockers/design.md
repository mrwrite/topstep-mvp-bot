## Context

The completed `consumer-ready-trading-bot-audit` change left live trading disabled and documented remaining blockers. Current code has paper-only execution, saved user integrations, provider capability metadata, basic health/status endpoints, demo seeding, and structured logs. It still lacks a centralized trading context service, persisted risk policies, kill switch records, paper equity ledger, full order lifecycle depth, provider reconciliation, live-readiness acknowledgement records, and critical responsive/accessibility tests.

## Architecture

### Trading Context

Introduce a `TradingContextService` as the only supported resolver for trading-sensitive operations. Inputs include user id, requested trading mode, integration id, account id, contract/symbol, source, strategy/bot session id when applicable, and required capabilities. Output is an immutable context object containing:

- user id;
- mode (`paper`, `demo`, `live_requested`, `live_blocked`, eventually `live`);
- broker integration and market-data integration;
- selected account id and account metadata;
- validated contract metadata;
- provider capability snapshot;
- provider health/diagnostic summary;
- risk policy id and kill switch state;
- readiness blockers.

Routes should not independently query integrations, accounts, contracts, or mode state after this service exists.

### Risk and Kill Switch

Persist risk settings per user/account/integration/mode. Risk checks should produce a `RiskDecision` record for every order intent, including allowed/blocked, rule ids, input metrics, account/equity snapshot id, and reason.

Persist kill switch records independently of transient bot state. A kill switch can be user-wide, account-scoped, integration-scoped, or bot-session scoped. If active, all order creation and bot automation for the affected scope must fail closed.

### Paper Ledger

Paper mode should simulate account state through durable ledger entries rather than only paper orders and positions. Ledger entries should cover starting balance, order reservation, fill, realized PnL, unrealized mark-to-market, fees/slippage assumptions, risk lockouts, and manual adjustments. The paper ledger must be separate from live provider state.

### Order Lifecycle

Order records need normalized states beyond submitted/accepted/filled:

- `created`
- `risk_blocked`
- `pending_submit`
- `submitted`
- `accepted`
- `rejected`
- `partially_filled`
- `filled`
- `cancel_requested`
- `canceled`
- `expired`
- `timeout_unknown`
- `reconciliation_required`
- `failed`

State transitions should be append-only order events. Terminal states must be clear. Unknown states must block retries until reconciliation finishes.

### Duplicate Protection

Idempotency keys are necessary but insufficient. Add duplicate detection over recent windows using normalized fingerprints:

- user id;
- account id;
- integration id;
- contract id/symbol;
- side;
- quantity;
- order type and prices;
- strategy/signal source;
- signal timestamp or candle timestamp.

Duplicate suppression must record the reason and return the existing order when appropriate.

### Reconciliation and Retry

Broker execution must never blindly retry after a timeout. A live submission should:

1. create a durable order in `pending_submit`;
2. submit with client order id/idempotency key where provider supports it;
3. persist provider response or timeout state;
4. reconcile unknown state through provider order lookup/open orders/fills/positions;
5. only retry when provider state proves no order was accepted.

Provider reconciliation jobs should be safe to run repeatedly and should block new live orders for an account when provider state conflicts with app state.

### Acknowledgements and Launch Gates

Live-readiness acknowledgements must be versioned, user/account scoped, time bounded, and invalidated when risk settings, terms, or provider capabilities materially change.

Launch gates should be implemented as an API/readiness surface that reports each gate as pass/fail, including schema, context service coverage, risk policy, kill switch, provider health, order lifecycle, reconciliation, acknowledgement, observability, and frontend readiness.

## Migration Approach

- Repair or replace the migration baseline so a fresh production-like database can be built from Alembic alone.
- Add additive migrations for new risk, ledger, acknowledgement, and audit tables.
- Add migration tests that create a fresh database, apply migrations, and verify required tables/indexes/constraints.
- Keep `ALLOW_CREATE_ALL=false` in production.

## Testing Strategy

- Unit tests for context resolution, risk rules, duplicate fingerprints, state transitions, and retry decisions.
- API tests for cross-user ownership, missing/inactive resources, risk lockouts, kill switch behavior, and live-blocking.
- Reconciliation tests using fake provider adapters for accepted, rejected, timeout, unknown, partial fill, canceled, and position mismatch cases.
- Migration tests for fresh database creation and schema constraints.
- Frontend tests for readiness checklist, live acknowledgement flow, lockout display, mobile layout, and keyboard/screen-reader access to stop controls.

## Rollout

1. Implement and enforce trading context while live remains disabled.
2. Add persisted risk and kill switch records while continuing paper-only execution.
3. Deepen paper ledger and order lifecycle until risk metrics are explainable.
4. Add reconciliation and retry design behind disabled live execution.
5. Add acknowledgements and launch gate surfaces.
6. Run full launch gate validation. Only after all gates pass should a separate change propose controlled live enablement.
