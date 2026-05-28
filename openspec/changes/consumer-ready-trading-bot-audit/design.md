## Context

This repository is a FastAPI backend with a Vite React frontend. The backend includes JWT auth, user-scoped saved `PlatformIntegration` records, an adapter factory, a TopStepX adapter with real API calls, placeholder adapters for Tradovate/NinjaTrader/IBKR/ETX, TradingView signal handling, contract fetching, analysis/backtesting helpers, and a scheduler route that streams bot output over SSE. The frontend has login/register, integration CRUD, active integration selection, contract loading, dashboard controls, market analysis, and backtest views.

The application is not consumer-ready for live trading. The largest blockers are missing pre-trade risk controls, global bot state shared across users, incomplete provider adapters advertised as capable, insufficient order/fill/position persistence, weak execution idempotency, fallback behavior that can hide integration failures, and missing deployment/observability/legal readiness.

## Goals / Non-Goals

**Goals:**

- Produce a strict readiness plan grounded in current repository behavior.
- Identify concrete P0-P3 findings with current behavior, risk/problem, required improvement, suggested implementation approach, priority, and whether each blocks consumer readiness.
- Define specs and phased tasks that can be implemented later.
- Keep live trading explicitly blocked until safety, isolation, execution, audit, and production requirements are satisfied.

**Non-Goals:**

- Implement the remediation in this change.
- Certify the strategy as profitable or suitable for any user.
- Provide legal advice or regulatory certification.
- Build complete real adapters for every broker in this audit phase.

## Audit Findings

### 1. Trading Integrations

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Active integration is only partly respected | `resolve_integration()` supports active/user-scoped integration selection, contracts use it, manual trade uses optional `integration_id`, dashboard active selection is saved, but SSE `startStream()` does not pass the active integration id to `/scheduler/run-bot`. | Users can believe one integration is selected while the bot resolves another active/recent integration or env fallback. | Every trading, market-data, account, contract, analysis, and webhook path must use an explicit selected integration or a persisted user default with clear precedence. | Add a `TradingContext` resolver that requires user id, mode, broker integration id, market data integration id, and account id; pass active integration from frontend SSE URL; reject ambiguous routes. | P0 | Yes |
| Webhook signal lookup is not user-authenticated | `/trading/webhook` accepts `signal_integration_id`, loads integration by id only, then routes by that integration's `user_id`; TradingView secret is optional if no stored secret exists. | Anyone who knows an integration id can route signals if secret is unset; signal source has no strong user/account binding. | Webhooks must require a provider-specific secret or signed token and must never execute without a verified signal integration owner and broker mapping. | Store generated webhook tokens, require constant-time secret comparison, scope broker mapping to the same user, add replay/idempotency keys, and record rejected attempts. | P0 | Yes |
| Placeholder providers are advertised as trading-capable | Provider capabilities list Tradovate, NinjaTrader, IBKR, and ETX as broker/market-data capable, but their adapters only validate non-empty credentials and `place_order()` raises `NotImplementedError`; `get_contracts()` inherits capability errors. | Users can configure providers that appear usable but fail at runtime, including during trading. | Provider capability metadata must reflect implemented, verified capabilities, separately from roadmap capabilities. | Introduce `implemented_capabilities`, `roadmap_capabilities`, and provider health/status; disable execution for unimplemented providers in API and UI. | P0 | Yes |
| TopStepX is the only real broker adapter | TopStepX has auth, contract search, account search, order placement, and bars; other providers are stubs; legacy `app/auth.py` and `app/projectx.py` still use env credentials. | Product claims multi-provider readiness without real support; legacy env-based code can bypass saved integrations. | Make TopStepX the only live-supported provider until others have tested adapters; isolate legacy env code to development/demo only. | Mark non-TopStepX providers as setup preview; remove env fallback in production; add adapter conformance tests before enabling each provider. | P0 | Yes |
| Contract fetching falls back silently | `/contracts` returns fallback symbols when no active integration or provider failure exists. | Users may trade symbols that were not validated for the selected broker/account. | Contract lists used for trading must come from selected broker/market-data provider or be clearly non-tradable demo data. | Return a blocking error for live mode; allow fallback contracts only in paper/demo mode with visible source labels. | P0 | Yes |
| Provider sessions are not cached or modeled | TopStepX gets a token for each call with no expiry tracking; provider-specific auth errors are surfaced as generic messages or exceptions. | Increased latency/rate-limit risk and poor recovery from expired credentials/session failures. | Provider sessions must track token expiry, refresh behavior, and normalized auth states. | Add provider session service with encrypted refresh material, per-provider auth state enum, retry/backoff, and health diagnostics. | P1 | No, if live remains disabled |

### 2. Trading Safety

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| No pre-trade risk engine | `/scheduler/execute-trade`, `/trading/test-trade`, webhook execution, and auto-trading call `adapter.place_order()` directly after minimal symbol/side/quantity checks. | A user can place oversized, repeated, or account-inappropriate trades. | Every order must pass centralized risk checks before broker submission. | Add `RiskPolicy` and `RiskDecision` service enforcing max daily loss, max trade size, max contracts, max open positions, buying power/equity checks, mode, market hours if applicable, and user confirmations. | P0 | Yes |
| No max daily loss/equity tracking | User model only stores RSI thresholds. No account equity, realized/unrealized PnL, or daily lockout exists. | Bot can continue trading after unacceptable losses. | Persist risk limits per user/account and enforce daily lockouts from broker/account/trade state. | Add tables for risk settings, account snapshots, daily risk state, and lockout events; integrate provider account APIs. | P0 | Yes |
| Global bot state is shared across users | `BOT_STATE` is a module-level dict for thresholds, auto trade, quantity, interval, and stop. | One user's config or stop command can affect another user's session. | Bot sessions must be user/account/integration scoped. | Replace global dict with persisted `BotSession` records and per-session cancellation tokens keyed by user id/session id. | P0 | Yes |
| Kill switch is global and incomplete | `/scheduler/stop-bot` has no auth and flips global `BOT_STATE["stop"]`. | Unauthorized or cross-user stop behavior; no provider-level cancel/flatten action. | Kill switch must be authenticated, user-scoped, auditable, and optionally flatten/cancel open orders. | Add authenticated `/bot-sessions/{id}/stop`, `/risk/kill-switch`, and provider cancel/flatten adapter methods where supported. | P0 | Yes |
| Paper vs live separation is ambiguous | TopStepX payloads hardcode `live: False` for contracts/history, but order placement uses provider order API; UI has "demo" badge and "Auto Trade" but no explicit live/paper enforcement. | Users may misunderstand whether real orders can be placed. | Trading mode must be explicit, persisted, and enforced in every execution path. | Add `trading_mode` (`paper`, `live_disabled`, `live`) and require acknowledgement plus production allowlist before live. | P0 | Yes |
| No duplicate-order protection | No idempotency keys, signal dedupe, recent signal window, or open-order check before submission. | Webhook retries, SSE loops, or UI double-clicks can place duplicate orders. | All trade actions must include idempotency and duplicate prevention. | Require client/server idempotency keys, hash signals, check recent accepted orders and open positions, and enforce cooldowns. | P0 | Yes |

### 3. Order Execution

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Only market orders are implemented | TopStepX adapter sends `type: 2` with no limit/stop fields; request models accept only symbol/side/quantity. | Users cannot place common protective or controlled orders; accidental market execution risk. | Support market, limit, stop, and stop-limit where provider supports them; reject unsupported order types. | Define normalized `OrderIntent` with order type, time-in-force, price, stop price, account, contract, mode, and client order id. | P1 | Yes for live readiness |
| No order/fill/position persistence | Trades are logged to `logs/trades.csv`; no DB tables for orders, fills, positions, or provider order ids. | Cannot reconcile execution, show accurate state, audit actions, or recover after restart. | Persist complete order lifecycle and position state per user/account/provider. | Add `orders`, `order_events`, `fills`, `positions`, and reconciliation jobs. | P0 | Yes |
| Success handling trusts raw provider response | Manual/auto routes mark CSV status based on `response.get("success")`; no fill confirmation or order status polling exists. | Accepted/rejected/partially filled states can be misreported. | Execution must distinguish submitted, accepted, rejected, partially filled, filled, canceled, and unknown. | Adapter must return normalized execution result and provider order id; poll/subscribe for status until terminal or timeout. | P0 | Yes |
| Failed-order handling is ad hoc | Some TopStepX HTTP errors become response objects; other adapter exceptions bubble to 500 or SSE log strings. | Users receive inconsistent errors and may not know whether an order was placed. | Normalize provider errors and classify retryable vs terminal vs unknown. | Add `ProviderError` taxonomy and route-level exception handling; log every failed attempt with correlation id. | P0 | Yes |
| No retry policy or reconciliation | TradingView client retries 429s, but broker execution has no idempotent retry/reconciliation strategy. | Network failures can produce duplicate or unknown orders. | Retry only when safe, with idempotency and provider reconciliation before resubmission. | Implement broker execution workflow: create pending order, submit with client id, verify provider state, reconcile unknowns, then decide retry. | P0 | Yes |

### 4. Strategy Engine

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Strategy is simplistic and partly inconsistent | `check_trade_signal()` returns BUY if RSI below threshold, SELL if above; moving averages are computed/logged but not used. | Users may assume multi-signal strategy sophistication that does not exist. | Strategy logic and UI must accurately describe implemented signals and limitations. | Rename current strategy to `rsi-threshold-v1`; add explicit config schema and strategy documentation. | P1 | No, if live disabled |
| Strategy config is incomplete | User stores only buy/sell thresholds; scheduler config is global; no per-integration/account strategy config. | Multi-user sessions can collide and cannot be reproduced. | Strategy config must be user/account/session scoped and versioned. | Add `strategy_configs` table with parameters, risk bindings, enabled mode, and version. | P0 | Yes |
| Backtesting is not production-grade | Backtest uses TradingView then TopStepX fallback, simple entry/exit logic, no fees/slippage/contracts/tick value/margin/session hours. | Metrics can be misleading and unsuitable for trading decisions. | Backtests must disclose assumptions and support realistic simulation parameters. | Add slippage/commission/tick value, contract metadata, session filters, drawdown, exposure, Sharpe-like metrics if appropriate, and clear warnings. | P1 | No |
| Paper trading simulation is missing | No paper order book, simulated fills, or paper account state exists. | Users cannot validate workflows safely before live. | Paper trading must be a first-class mode with persisted simulated orders/fills/positions/equity. | Build a paper execution adapter that uses market data and deterministic fill rules. | P0 | Yes |
| No strategy guardrails or accuracy reporting | No min sample size, stale data checks, indicator NaN checks beyond scheduler column existence, or live vs backtest drift reporting. | Strategy may act on poor data or report unreliable performance. | Strategy engine must block on stale/invalid data and report metrics with confidence context. | Add data-quality gate, stale bar detection, min bars, metric dashboard, and strategy event logs. | P1 | No |

### 5. User Experience

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Product still reads as TopStep MVP | README, page titles, index title, dashboard eyebrow, and integration labels use TopStep-specific copy. | Multi-provider consumer product appears inconsistent and unfinished. | Use generic broker/trading bot terminology where provider-specific wording is not required. | Rename UI chrome to provider-neutral language; keep TopStepX only in provider forms/status. | P2 | No |
| Live/paper clarity is insufficient | UI has "demo" badge, "Signal Only", "Auto Trade", fallback contract notices, and manual prompts, but no enforced live/paper state. | Users may misunderstand risk exposure. | Mode must be prominent, persistent, and impossible to confuse. | Add mode selector with paper default, live disabled until prerequisites pass, visible account/provider/mode banner, and confirmation modals. | P0 | Yes |
| Contract/account selection is incomplete | Contract select shows symbols; account is metadata only; TopStepX adapter picks first active account. | User may trade wrong account or instrument. | Users must explicitly select account and validated contract for the selected provider/mode. | Add account fetch endpoint, account selector, contract detail view, and reject execution without selected account/contract ids. | P0 | Yes |
| Error/loading/empty states are uneven | Integration load errors are generic; contract fallback can appear as options; logs contain mojibake characters; analysis/backtest duplicate UI sections exist. | Consumer experience feels unreliable and can hide dangerous state. | Provide clear, actionable, provider-specific states without corrupted text. | Normalize API errors, fix encoding/copy, remove duplicated dashboard result blocks, and add empty/loading/skeleton states. | P1 | No |
| Mobile responsiveness and accessibility are unverified | CSS exists but no automated or manual responsive evidence was found. | Day traders may use tablets/mobile; dense dashboard can break. | Validate dashboard and integration flows at common breakpoints. | Add Playwright responsive smoke tests and fix overflow, table, and control layout issues. | P2 | No |

### 6. Authentication and User Data

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| JWT is short-lived with no refresh/session management | Access token expires after 30 minutes; frontend stores it in localStorage; no refresh/logout invalidation. | Users can be interrupted mid-session; localStorage increases XSS token exposure. | Implement secure session lifecycle suitable for trading workflows. | Use httpOnly secure cookies or hardened token storage, refresh tokens, logout revocation, session expiry UX, and CSRF strategy if cookie-based. | P1 | No, if live disabled |
| Some routes bypass normal auth | `/scheduler/run-bot` takes `access_token` query param for EventSource; `/scheduler/update-config` and `/scheduler/stop-bot` have no auth. | Tokens leak in URLs/logs and unauthenticated users can mutate global bot state. | All bot control routes must be authenticated and user-scoped. | Replace EventSource auth query with session id or cookie auth; add auth dependencies to update/stop; store per-user bot sessions. | P0 | Yes |
| Credential encryption depends on app secret fallback | Credentials use Fernet key or derive from `SECRET_KEY`. | Secret rotation can break credentials; weak shared secret increases blast radius. | Use explicit credentials encryption key with rotation plan. | Require `CREDENTIALS_ENCRYPTION_KEY` in production, add key id/version, rotation migration, and startup validation. | P0 | Yes |
| Multi-user isolation is partial | Integration CRUD filters by user and tests cover isolation; scheduler global state, webhook id lookup, CSV logs, and env fallback are not user-isolated. | Users can affect or observe shared bot behavior and trade logs. | Every account, contract, order, bot session, audit log, and diagnostic must be user-scoped. | Add user/account foreign keys to all trading tables and authorization checks in every route. | P0 | Yes |

### 7. Backend Architecture

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Route/service boundaries are thin | Routes call adapters directly; trading logic is spread across `scheduler.py`, `trading_routes.py`, `contracts.py`, and legacy TopStep modules. | Hard to enforce safety consistently. | All execution must flow through a small set of domain services. | Add `TradingContextService`, `RiskService`, `OrderExecutionService`, `PositionService`, `ProviderRegistry`, and `AuditService`. | P0 | Yes |
| Adapter interface is too small | Base adapter only has healthcheck/contracts/account/place_order. | Cannot support accounts, order status, fills, positions, cancel/flatten, sessions, or provider diagnostics. | Expand adapter contract and test it per provider. | Define methods for auth, accounts, contracts, quote/bars, submit, get order, list open orders, positions, cancel, flatten, and diagnostics. | P1 | Yes for multi-provider |
| Database schema is MVP-only | Users and integrations exist; no trading domain tables. Initial migration is empty and app calls `create_all()`. | Production schema state is unreliable and cannot support audit/reconciliation. | Use Alembic-only migrations and normalized trading tables. | Remove production reliance on `create_all()`, repair baseline migration path, add trading schema migrations and migration tests. | P0 | Yes |
| Validation is incomplete | Many request fields are strings/ints without strict enum/range validation. | Bad side, quantity, symbol, mode, and provider data can reach adapters. | Validate all trading inputs with strict schemas and provider constraints. | Use Pydantic enums, min/max, regex/symbol validation, and cross-field checks; return structured errors. | P0 | Yes |
| Scheduler does not scale | Long-running SSE loop lives inside web process with per-request DB setup and global state. | Not reliable across multiple workers, restarts, or Railway/Vercel runtime limits. | Move bot sessions to a worker/job model with durable state. | Use a background worker/queue or scheduler service, heartbeat, lease locking, and durable session events. | P1 | Yes for production auto-trading |

### 8. Observability

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Trade audit is CSV-only and incomplete | `logger.py` writes symbol/side/quantity/price/status/response to `logs/trades.csv`; webhook writes raw CSV row before validation. | Not user-scoped, not tamper-resistant, not queryable, and logs unvalidated requests. | Every trade action and decision must be stored in DB with user/account/provider context. | Add append-only `trade_audit_events` table and structured log correlation ids. | P0 | Yes |
| Logging is inconsistent | Mix of `print`, Python logging, SSE text, and CSV; some output includes corrupted characters and potentially sensitive provider responses. | Hard to debug; may leak secrets or confuse users. | Standardize structured logging with redaction. | Configure JSON logs, redaction filters, request ids, provider ids, order ids, and exception handlers. | P1 | No |
| Health checks are missing | FastAPI app has no explicit `/health`, DB check, provider diagnostics, or frontend status route. | Deployments cannot be monitored reliably. | Provide app, database, migration, and provider health endpoints. | Add `/health/live`, `/health/ready`, `/diagnostics/providers`, and admin-only provider test endpoints. | P1 | No |
| User-visible status is shallow | Frontend shows connected/disconnected and session state but not provider/account/order health. | Users cannot tell whether trading is safe to start. | Dashboard must show readiness status before enabling trading. | Add readiness checklist: auth, broker, account, contract, mode, risk policy, market data, paper/live status. | P0 | Yes |

### 9. Production Readiness

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Deployment config is absent | No root Railway config, Vercel config, Dockerfile, Procfile, or deployment scripts were found. | Deployments rely on manual assumptions. | Define reproducible backend/frontend deployments. | Add Railway service docs/config, Vercel env docs/config, build/start commands, migration command, and runtime health checks. | P1 | No, but blocks launch |
| Env requirements are documented but not enforced per environment | README lists env vars; startup requires `DATABASE_URL` and `SECRET_KEY`; production does not validate all required vars. | Misconfigured deployment can start partially or fail at runtime. | Add production startup validation and env matrix. | Create config module with required/optional vars by mode and fail-fast validation. | P0 | Yes |
| CORS is permissive by method/header | CORS origin list is env-driven/defaulted, but methods and headers are wildcard. | Larger attack surface for consumer app. | Tighten CORS/security headers in production. | Restrict methods/headers, add trusted origins, security headers, HTTPS-only cookies if used. | P1 | No |
| Rate limiting is missing | No API/user/webhook rate limiting except TradingView client retry behavior. | Brute force, webhook flooding, duplicate orders, and provider quota exhaustion. | Rate limit auth, webhook, trading, and provider proxy routes. | Add per-IP/user/provider rate limits and webhook burst controls. | P0 | Yes |
| Backup/recovery/monitoring are undefined | No backup, restore, alerts, or incident plan exists. | Trade/audit/account state may be lost. | Define backup, restore, monitoring, and incident response requirements. | Use managed Postgres backups, migration rollback docs, alerting for failed orders/provider errors, and runbooks. | P1 | No |

### 10. Legal / Risk Communication

| Finding | Current behavior | Risk/problem | Required improvement | Suggested implementation approach | Priority | Blocks readiness |
| --- | --- | --- | --- | --- | --- | --- |
| Risk disclosures are missing | README and UI do not include clear paper/live disclaimers, no guaranteed profit warning, or user responsibility acknowledgement. | Consumer users may misunderstand financial risk. | Add clear risk communication before trading and in terms/privacy surfaces. | Add onboarding acknowledgement, live-mode confirmation, persistent mode warnings, terms/privacy links, and no-profit-guarantee copy. | P0 | Yes |
| Live trading confirmation is insufficient | Manual approval prompt exists only in signal-only mode; auto trade can be toggled with no live risk acknowledgement. | Users can enable automation without explicit acceptance of risk. | Require explicit per-account live trading enablement and confirmations. | Add live-trading unlock flow with risk checklist, account selection, max loss, emergency stop, and acknowledgement record. | P0 | Yes |

## Decisions

1. **Live trading remains blocked by default.**
   - Rationale: Missing P0 safety, user scoping, audit, and execution lifecycle controls make live consumer trading unsafe.
   - Alternative considered: Keep current TopStepX market order path enabled while adding warnings. Rejected because warnings do not prevent duplicate, oversized, cross-user, or unaudited trades.

2. **All trading paths must use centralized domain services.**
   - Rationale: Safety cannot be reliably enforced when routes call provider adapters directly.
   - Alternative considered: Add checks inside each route. Rejected because webhook, scheduler, manual trade, and test trade would drift.

3. **Provider capabilities must distinguish implemented vs planned.**
   - Rationale: The UI/API currently advertise placeholder providers as capable. Consumer readiness requires truthful provider state.
   - Alternative considered: Keep capability list as target roadmap. Rejected because it misleads route resolution and users.

4. **Paper trading becomes the default execution mode.**
   - Rationale: Users need to validate workflows without live risk, and the app needs a safe investor/demo path.
   - Alternative considered: Use provider sandbox flags only. Rejected because provider sandboxes vary and do not replace app-owned simulation/audit.

5. **Execution state moves to durable database records.**
   - Rationale: CSV logs and in-memory state are insufficient for reconciliation, audit, recovery, and multi-user operation.
   - Alternative considered: Keep CSV logs for early launch. Rejected for consumer trading because they are not secure, queryable, or relational.

## Risks / Trade-offs

- **Provider API variance** -> Use a normalized adapter contract plus provider-specific capability flags and conformance tests.
- **More database complexity** -> Introduce migrations in phases, beginning with P0 risk/order/audit/session tables.
- **Slower path to live trading** -> Preserve user trust by defaulting to paper/demo until safety gates pass.
- **SSE auth limitations** -> Prefer authenticated bot session resources and cookie/session-compatible streaming; document fallback if EventSource header limitations remain.
- **Backtest overconfidence** -> Make assumptions explicit and block performance claims until simulation is materially improved.

## Migration Plan

1. Freeze live execution behind a feature flag until P0 requirements are implemented.
2. Add production configuration validation and disable env broker fallback outside development.
3. Create database migrations for user-scoped trading domain tables.
4. Route all manual, webhook, scheduler, and test execution through `OrderExecutionService`.
5. Add risk engine and paper execution adapter before restoring any live order pathway.
6. Add provider conformance tests, TopStepX status reconciliation, and truthful provider capability flags.
7. Add frontend readiness checklist, account/contract selectors, risk acknowledgement, and mode enforcement.
8. Add deployment configs, health checks, monitoring, backups, and legal/risk surfaces before consumer launch.

Rollback strategy: keep new live trading feature flag disabled by default; migrations should be additive during early phases; retain existing integration CRUD while redirecting execution through new services.

## Open Questions

- Which provider should be the first production-supported broker after TopStepX: Tradovate, NinjaTrader, IBKR, or ETX?
- Should live trading be offered to all users, allowlisted users, or only internal/investor demo accounts initially?
- Which exact risk defaults should ship for day traders by account type and provider?
- What legal entity, terms, privacy policy, support process, and incident escalation path will govern consumer use?
- Which hosting split is intended: FastAPI on Railway and React on Vercel, or a different production topology?
