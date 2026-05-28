## 1. Phase 1: Critical Safety and User-Scoping Fixes

- [x] 1.1 Add a production feature flag that disables all live broker order placement by default until P0 readiness gates pass.
- [x] 1.2 Remove unauthenticated access from `/scheduler/update-config` and `/scheduler/stop-bot`.
- [x] 1.3 Replace query-string JWT usage for `/scheduler/run-bot` with an authenticated, user-scoped bot session approach.
- [x] 1.4 Replace module-level `BOT_STATE` with per-user/per-session bot state persisted or keyed by authenticated user and session id.
- [x] 1.5 Ensure dashboard `startStream()` passes the selected active integration/session context to the backend.
- [ ] 1.6 Add a centralized `TradingContextService` that resolves user, mode, broker integration, market-data integration, account, and contract.
- [x] 1.7 Add strict request validation for side, quantity, symbol/contract, integration id, account id, order type, and trading mode.
- [x] 1.8 Disable env broker fallback outside development and make fallback use visible in API responses and UI.
- [x] 1.9 Require stored webhook secrets or signed tokens for signal integrations; reject unsecured webhooks.
- [x] 1.10 Add webhook idempotency and replay protection before routing signals to broker execution.
- [ ] 1.11 Create initial risk settings schema for max daily loss, max trade size, max contracts, max open positions, and live-trading enabled state.
- [x] 1.12 Implement `RiskService` and route every manual, webhook, test, and bot order through it before provider submission.
- [ ] 1.13 Add user/account-scoped kill switch records and authenticated stop endpoints.
- [ ] 1.14 Add tests proving one user cannot read, mutate, stop, route, or trade through another user's integrations, accounts, bot sessions, orders, or audit events.
- [x] 1.15 Add paper/live mode enforcement and block live mode unless risk acknowledgement, selected account, selected contract, risk settings, and provider health are present.

## 2. Phase 2: Broker/Integration Abstraction Hardening

- [x] 2.1 Split provider metadata into implemented capabilities and roadmap capabilities.
- [x] 2.2 Mark Tradovate, NinjaTrader, IBKR, and ETX live trading/market-data capabilities unavailable until real adapters pass conformance tests.
- [x] 2.3 Expand the provider adapter interface for auth/session state, accounts, contracts, bars/quotes, submit order, get order, open orders, fills, positions, cancel, flatten, and diagnostics.
- [x] 2.4 Add adapter conformance test fixtures and require each enabled provider to pass them before capability exposure.
- [x] 2.5 Add provider-specific normalized error taxonomy for auth, validation, rate limit, provider unavailable, rejected order, timeout, and unknown state.
- [x] 2.6 Add TopStepX session caching with expiry tracking and safe refresh behavior.
- [x] 2.7 Add explicit account retrieval and account selection endpoints for providers that support account info.
- [x] 2.8 Change TopStepX order placement to require selected account id instead of automatically using the first active account.
- [x] 2.9 Change contract fetching to reject live fallback contracts and label demo/paper fallback contracts as non-live.
- [x] 2.10 Add provider health and credential validation endpoints for the integrations UI.
- [x] 2.11 Remove or quarantine legacy env-based TopStepX modules from production execution paths.

## 3. Phase 3: Trading Execution Reliability

- [x] 3.1 Add normalized `OrderIntent`, `OrderRecord`, `OrderEvent`, `Fill`, and `Position` database models and Alembic migrations.
- [x] 3.2 Add an `OrderExecutionService` that creates pending orders, runs risk checks, submits to paper or broker adapter, and records every state transition.
- [x] 3.3 Add client/server idempotency keys to manual orders, webhooks, and bot-generated strategy orders.
- [ ] 3.4 Add support for market, limit, stop, and stop-limit schemas with provider capability checks.
- [ ] 3.5 Add provider order status tracking and normalized states: pending, accepted, rejected, partially filled, filled, canceled, expired, failed, and unknown.
- [x] 3.6 Add fill confirmation workflow before showing an order as filled.
- [ ] 3.7 Add safe retry policy that reconciles unknown provider state before any resubmission.
- [ ] 3.8 Add position reconciliation against provider state for live accounts.
- [x] 3.9 Add duplicate-order prevention windows for repeated bot signals, webhook retries, and UI double submissions.
- [x] 3.10 Replace CSV trade logging as the source of truth with database audit/order records while keeping optional local logs for development only.
- [ ] 3.11 Add execution tests for accepted, rejected, timeout, unknown, duplicate, partial fill, and provider-unavailable cases.

## 4. Phase 4: Strategy and Paper-Trading Validation

- [x] 4.1 Rename and document the current strategy as `rsi-threshold-v1`.
- [x] 4.2 Persist versioned strategy configurations per user, account, mode, symbol scope, and bot session.
- [x] 4.3 Remove misleading moving-average/momentum claims until those rules are actually part of signal generation.
- [x] 4.4 Add data-quality gates for stale bars, missing candles, insufficient sample size, NaN indicators, and unsupported resolutions.
- [ ] 4.5 Build a paper execution adapter with simulated orders, fills, positions, equity, and PnL.
- [x] 4.6 Add strategy guardrails for cooldown, max signals per period, no-trade windows, and risk-policy binding.
- [ ] 4.7 Improve backtesting with slippage, commissions, tick value, contract metadata, drawdown, exposure, and simulation assumptions.
- [x] 4.8 Add clear warnings that backtest and paper results do not guarantee live performance.
- [x] 4.9 Add tests comparing strategy behavior in live-blocked, paper, and backtest modes.

## 5. Phase 5: Consumer UX Polish

- [x] 5.1 Replace hardcoded TopStep product chrome with provider-neutral product terminology while keeping provider-specific labels where relevant.
- [ ] 5.2 Add dashboard readiness checklist for provider, credentials, account, contract, market data, risk policy, mode, and kill switch state.
- [x] 5.3 Add explicit paper/demo/live/signal-only mode selector and persistent mode banner.
- [x] 5.4 Add account selector and contract detail selector tied to the selected provider and trading mode.
- [x] 5.5 Disable trading controls when readiness prerequisites are missing or provider capability is unavailable.
- [ ] 5.6 Add live-trading acknowledgement and confirmation UX with stored acknowledgement records.
- [x] 5.7 Improve integration cards with implemented/roadmap capability labels, health status, credential status, and account availability.
- [x] 5.8 Replace generic error messages with actionable provider/risk/order messages from normalized backend errors.
- [x] 5.9 Fix corrupted text/encoding artifacts in UI logs, labels, README, and source comments.
- [x] 5.10 Remove duplicated analysis/backtest result sections from the dashboard.
- [x] 5.11 Add robust loading and empty states for auth, integrations, providers, accounts, contracts, orders, bot sessions, analysis, and backtests.
- [ ] 5.12 Add responsive and accessibility tests for dashboard, integrations, auth, and emergency stop controls.

## 6. Phase 6: Production Readiness

- [x] 6.1 Add environment-specific configuration validation for development, test, demo, and production.
- [x] 6.2 Require explicit `CREDENTIALS_ENCRYPTION_KEY` in production and document credential rotation.
- [x] 6.3 Replace production reliance on `models.Base.metadata.create_all()` with Alembic migration readiness checks.
- [x] 6.4 Repair or document the migration baseline because the initial migration currently contains no table creation.
- [x] 6.5 Add `/health/live` and `/health/ready` endpoints covering app, database, migration state, and critical config.
- [x] 6.6 Add Railway backend deployment config or documentation with build, start, env, migration, health check, and worker assumptions.
- [x] 6.7 Add Vercel frontend deployment config or documentation with `VITE_API_URL`, allowed origins, and build command.
- [x] 6.8 Tighten production CORS origins, methods, headers, and security headers.
- [x] 6.9 Add rate limiting for auth, webhook, trading, contract, analysis, and provider diagnostic routes.
- [x] 6.10 Add structured JSON logging with redaction, request ids, user/session/order correlation, and provider error classification.
- [x] 6.11 Add monitoring/alerting for failed orders, risk lockouts, provider auth failures, webhook failures, and job/session failures.
- [x] 6.12 Document backup, restore, migration rollback, incident response, and trading disable procedures.

## 7. Phase 7: Investor/Demo Package

- [ ] 7.1 Create a demo mode that uses paper trading or mocked providers only and cannot route to live broker adapters.
- [ ] 7.2 Seed safe demo integrations, demo accounts, demo contracts, sample strategy configs, and sample audit/order history.
- [ ] 7.3 Add investor-facing dashboard flow showing readiness checklist, paper orders, risk controls, audit trail, and provider status.
- [ ] 7.4 Add paper trading disclaimer, live trading risk disclaimer, no guaranteed profit language, and user responsibility acknowledgement.
- [ ] 7.5 Add terms/privacy placeholders or links required before consumer account rollout.
- [ ] 7.6 Add demo reset tooling that clears only demo data and preserves production safeguards.
- [ ] 7.7 Add a smoke test script covering register/login, create integration, select account/contract, start paper session, place paper order, stop session, and view audit trail.
- [ ] 7.8 Produce a launch-readiness checklist that separates demo-ready, paper-ready, and live-ready criteria.
