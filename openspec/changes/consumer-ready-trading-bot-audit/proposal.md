## Why

The current application is a useful MVP for experimenting with a TopStepX-centered trading bot, but it is not ready for real day traders or live consumer use. A strict readiness audit is needed before implementation continues so future work is sequenced around user safety, account isolation, execution reliability, broker abstraction, and production operations.

This change does not implement the remediation. It creates a professional product and engineering readiness plan that identifies the current gaps, risks, required improvements, and implementation phases needed before the app can be considered consumer-ready.

## What Changes

- Add a repository-grounded readiness assessment covering frontend, backend, authentication, integrations, contracts, trading routes, scheduler, strategy, backtesting, database models, migrations, observability, deployment, and legal/risk communication.
- Define consumer-readiness requirements for broker integrations, trading safety, order execution, strategy validation, user experience, production readiness, and observability.
- Create a phased implementation checklist suitable for later Codex execution.
- Mark live trading as blocked until P0 user-scoping, risk-control, execution, audit, and production-readiness requirements are implemented and verified.
- Identify hardcoded TopStepX assumptions and generic broker/product terminology cleanup needed for a multi-provider consumer product.
- Document provider readiness gaps for TopStepX, Tradovate, NinjaTrader, TradingView, IBKR, and ETX.

## Capabilities

### New Capabilities

- `trading-integrations`: Provider selection, credential/session handling, contract/account retrieval, provider error normalization, and support readiness across TopStepX, Tradovate, NinjaTrader, TradingView, IBKR, and ETX.
- `trading-safety`: Pre-trade controls, account/equity checks, live-vs-paper separation, duplicate-order prevention, confirmation behavior, and kill switch requirements.
- `order-execution`: Reliable order submission, status tracking, fill confirmation, retries, idempotency, position tracking, and trade-action audit behavior.
- `strategy-engine`: Strategy configuration, RSI/moving-average/momentum readiness, guardrails, backtesting quality, paper simulation, and reporting requirements.
- `user-experience`: Dashboard, integration, contract, account, trading-mode, errors/loading/empty states, mobile readiness, investor/demo readiness, and terminology cleanup.
- `production-readiness`: Deployment, environment variables, CORS/security, migrations, rate limiting, secrets, backups, monitoring, and legal/risk communication requirements.
- `observability`: Application logging, trade audit trail, provider diagnostics, health checks, user-visible status indicators, and admin/debug tooling.

### Modified Capabilities

- None. The repository currently has no archived base specs under `openspec/specs/`, so this audit introduces new capability specs.

## Impact

- Backend: `app/auth_routes.py`, `app/integrations_routes.py`, `app/integrations_service.py`, `app/providers/*`, `app/contracts.py`, `app/trading_routes.py`, `app/scheduler.py`, `app/backtesting.py`, `app/strategy.py`, `app/models.py`, `app/database.py`, `app/main.py`, `logger.py`.
- Frontend: `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/Integrations.tsx`, `frontend/src/hooks/useActiveIntegrationContracts.ts`, `frontend/src/api.ts`, `frontend/src/api/contracts.ts`, `frontend/src/styles.css`, auth pages, and product copy.
- Database and migrations: current Alembic migrations, user/integration schema, and future schemas for risk settings, accounts, orders, fills, positions, bot sessions, audit logs, strategy configs, paper/live environments, and provider diagnostics.
- Operations: Railway/Vercel deployment assumptions, environment variable documentation, CORS, migrations on deploy, monitoring, backup/recovery, and incident response.
- Legal/product: paper/live risk disclosures, no-profit-guarantee language, user responsibility confirmation, terms/privacy needs, and consumer-facing warnings.
