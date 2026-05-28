## Why

The `consumer-ready-trading-bot-audit` change made the app safer for paper trading and investor demos, but it intentionally left several items incomplete because they are deeper live-readiness blockers. Live trading must remain disabled until these blockers are implemented, tested, and validated together.

This change narrows the remaining work into a strict live-readiness plan. It focuses on ownership-safe trading context resolution, persisted risk controls, kill switch records, paper ledger depth, richer order lifecycle states, duplicate prevention beyond idempotency, retry/reconciliation behavior, user acknowledgements, readiness gates, migration discipline, and responsive/accessibility evidence.

## What Changes

- Define a focused implementation plan for the remaining blockers that prevent controlled live trading.
- Add requirements for a centralized `TradingContextService` used by every manual, scheduler, webhook, strategy, contract, account, and order path.
- Add persisted risk settings, daily risk state, account/equity snapshots, kill switch records, and audit events.
- Deepen paper order simulation with account ledger, equity, realized/unrealized PnL, and richer order states.
- Define live order status tracking, timeout handling, duplicate suppression, provider reconciliation, and retry rules that fail closed.
- Add live-readiness acknowledgement records and launch gate criteria.
- Add UI requirements for a full readiness checklist, risk lockouts, live acknowledgement flow, and responsive/accessibility test coverage.
- Add production migration baseline cleanup and readiness checks that block trading when schema state is unsafe.

## Non-Goals

- Do not enable live trading in this change.
- Do not add real broker live execution as part of planning.
- Do not expand provider support beyond existing adapter capability metadata.
- Do not certify profitability, trading suitability, or regulatory compliance.
- Do not replace legal review; this change only defines required product/legal acknowledgement surfaces.

## Live Trading Policy

Live trading SHALL remain blocked until every P0 task in this change is complete, tests pass, OpenSpec validation passes, and a final launch gate explicitly confirms:

- user/account/integration/contract context is resolved through one service;
- risk settings and kill switches are persisted and enforced;
- account/equity state is available or live trading is blocked;
- order lifecycle, duplicate prevention, retries, and reconciliation are safe;
- live acknowledgement records are current and scoped;
- migration baseline and production readiness checks are clean;
- UI readiness checklist blocks unsafe actions;
- responsive/accessibility coverage exists for critical trading and stop controls.

## Impact

- Backend domain services: `app/trading_context.py`, `app/trading_safety.py`, `app/paper_execution.py`, future `app/risk_service.py`, `app/order_execution.py`, reconciliation worker/job modules, and route integrations in `scheduler.py`, `trading_routes.py`, `contracts.py`, and `integrations_routes.py`.
- Database/migrations: risk settings, daily risk state, kill switch events, account snapshots, paper ledger entries, expanded order lifecycle fields/events, acknowledgement records, audit/reconciliation records, and migration baseline repair.
- Frontend: dashboard readiness checklist, live acknowledgement UX, risk lockout display, kill switch status/control, responsive/accessibility coverage, and operational status surfaces.
- Tests: backend ownership/risk/order/reconciliation tests, migration tests, frontend build and responsive/accessibility smoke tests, and launch gate validation.

## Success Criteria

- Live mode remains blocked until the launch gate reports all required P0 checks passing.
- Every trading path uses the same resolved trading context and rejects ambiguous, inactive, unsupported, or cross-user resources.
- Risk decisions are persisted and explainable.
- Kill switches are durable, user/account scoped, and audit visible.
- Paper simulation has enough ledger depth to validate risk, equity, and PnL flows before live.
- Unknown live provider states are reconciled before retry or user-facing completion.
- The UI makes readiness blockers impossible to miss and disables unsafe trading actions.
