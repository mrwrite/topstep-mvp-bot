## Phase 1: Trading Context and Ownership Hardening

- [x] 1.1 [P0] Implement `TradingContextService` for manual, scheduler, webhook, strategy, contract, account, and order paths.
  - Why it blocks live readiness: live trading cannot be safe while routes resolve users, integrations, accounts, contracts, mode, and provider health independently.
  - Acceptance criteria: every trading-sensitive route receives a context object or fails closed with readiness blockers; no route directly falls back to active/default integration for execution without the service.
  - Tests required: unit tests for explicit integration, active integration, inactive integration, missing credentials, unsupported capabilities, provider mismatch, missing account, missing contract, and live mode blocked.
- [x] 1.2 [P0] Enforce user ownership for all context resources and reject cross-user account, integration, contract, order, bot session, and strategy references.
  - Why it blocks live readiness: cross-user resource leakage can route or stop the wrong user's trading.
  - Acceptance criteria: all context queries include user id; cross-user references return 404/403 without revealing resource existence.
  - Tests required: API tests with two users for integrations, accounts metadata, contracts, bot sessions, strategy configs, orders, positions, and audit events.
- [x] 1.3 [P0] Add route coverage tests proving manual, scheduler, webhook, bot, contract, account, and strategy execution paths all call `TradingContextService`.
  - Why it blocks live readiness: bypass paths undermine safety gates.
  - Acceptance criteria: tests fail if any trading-sensitive route bypasses context resolution.
  - Tests required: monkeypatch/spy tests or dependency-injection tests for each route family.
- [x] 1.4 [P1] Return structured readiness blockers from context resolution for frontend display.
  - Why it blocks live readiness: users need clear reasons actions are disabled.
  - Acceptance criteria: context failures return stable codes such as `missing_account`, `provider_unhealthy`, `risk_policy_missing`, and `live_disabled`.
  - Tests required: response shape tests and frontend mapping tests.

## Phase 2: Persisted Risk Settings and Kill Switch

- [x] 2.1 [P0] Add Alembic migrations for risk settings, daily risk state, risk decisions, and risk lockout events.
  - Why it blocks live readiness: risk rules must survive restarts and be auditable per account.
  - Acceptance criteria: schema supports max daily loss, max trade size, max contracts, max open positions, allowed modes, reset policy, and effective timestamps.
  - Tests required: migration tests, model tests, uniqueness/scope tests, and risk setting CRUD tests.
- [x] 2.2 [P0] Enforce persisted risk settings before every paper or live order intent.
  - Why it blocks live readiness: live orders cannot rely on hardcoded defensive limits.
  - Acceptance criteria: missing or disabled risk settings block live; paper uses safe defaults only when explicitly marked as paper/demo.
  - Tests required: order tests for missing policy, exceeded quantity, exceeded position, max daily loss, inactive policy, and paper default behavior.
- [x] 2.3 [P0] Add persisted user/account/integration kill switch records and authenticated stop endpoints.
  - Why it blocks live readiness: stop state must be durable, scoped, and audit visible.
  - Acceptance criteria: active kill switch blocks new orders and bot sessions in scope; stop endpoint records actor, reason, scope, timestamp, and clear/reset state.
  - Tests required: API tests for account kill switch, user-wide switch, cross-user isolation, bot stop interaction, and order blocking.
- [x] 2.4 [P0] Add account/equity checks to risk decisions for live mode and fail closed when provider account state is unavailable.
  - Why it blocks live readiness: order size and daily loss cannot be evaluated without account state.
  - Acceptance criteria: live mode requires fresh account/equity snapshot; stale/unavailable data blocks live order creation.
  - Tests required: fake provider tests for fresh equity, stale equity, missing buying power, provider auth failure, and provider unavailable.
- [x] 2.5 [P1] Add risk decision audit and user-visible lockout reason APIs.
  - Why it blocks live readiness: users and support need explainable risk lockouts.
  - Acceptance criteria: risk decisions are queryable by user/account/order and redact provider-sensitive details.
  - Tests required: audit visibility tests and lockout endpoint tests.

## Phase 3: Paper Ledger and Order Lifecycle Depth

- [x] 3.1 [P0] Add paper account ledger, account snapshots, and equity/PnL models with migrations.
  - Why it blocks live readiness: paper mode must validate risk/equity workflows before any controlled live rollout.
  - Acceptance criteria: ledger records starting balance, reservations, fills, realized PnL, unrealized marks, fees/slippage assumptions, and adjustments.
  - Tests required: migration tests, ledger balance tests, PnL tests, and user/account isolation tests.
- [x] 3.2 [P0] Expand order lifecycle states and enforce valid state transitions.
  - Why it blocks live readiness: live execution requires durable non-terminal, terminal, failed, and unknown states.
  - Acceptance criteria: orders support created, risk_blocked, pending_submit, submitted, accepted, rejected, partially_filled, filled, cancel_requested, canceled, expired, timeout_unknown, reconciliation_required, and failed.
  - Tests required: state machine tests for valid and invalid transitions, partial fills, cancel, timeout, and rejection.
- [x] 3.3 [P0] Add duplicate-order protection beyond idempotency using normalized order/signal fingerprints and time windows.
  - Why it blocks live readiness: repeated bot signals, webhook retries, and UI double-clicks can still duplicate orders with new idempotency keys.
  - Acceptance criteria: duplicate fingerprints suppress or require confirmation before creating a second order; suppression is audited.
  - Tests required: webhook retry, UI repeat, bot same-candle repeat, same key different payload, and allowed distinct order tests.
- [x] 3.4 [P1] Support market, limit, stop, and stop-limit schemas in paper mode with provider capability metadata.
  - Why it blocks live readiness: order schemas must be validated before provider routing exists.
  - Acceptance criteria: unsupported order types are rejected; paper mode simulates valid order types according to documented assumptions.
  - Tests required: schema validation, limit fill, stop trigger, stop-limit non-fill, unsupported provider capability tests.
- [x] 3.5 [P1] Replace CSV trade logging as any remaining authoritative source with queryable order/audit APIs.
  - Why it blocks live readiness: CSV logs are not sufficient for live audit or support.
  - Acceptance criteria: every paper order action has DB order events and audit events; CSV is optional development output only.
  - Tests required: order audit API tests and CSV-disabled production tests.

## Phase 4: Broker Reconciliation and Retry Design

- [x] 4.1 [P0] Add provider reconciliation service for order status, fills, open orders, and positions.
  - Why it blocks live readiness: provider state is authoritative for live accounts and must be reconciled before decisions.
  - Acceptance criteria: service can reconcile by provider order id, client order id, account, and symbol; mismatches create reconciliation_required state.
  - Tests required: fake provider tests for accepted, filled, partial fill, canceled, rejected, missing order, and mismatched position.
- [x] 4.2 [P0] Implement timeout and unknown-state handling that blocks blind retries.
  - Why it blocks live readiness: retrying after unknown submission can create duplicate live orders.
  - Acceptance criteria: network timeout after possible submission marks order `timeout_unknown`; retry is blocked until provider lookup proves no accepted order exists.
  - Tests required: timeout-before-send, timeout-after-send, lookup-found, lookup-not-found, lookup-provider-down tests.
- [x] 4.3 [P0] Add safe retry policy with explicit retryability classification.
  - Why it blocks live readiness: only known-safe failures should be retried.
  - Acceptance criteria: retry policy distinguishes validation rejection, auth failure, rate limit, provider unavailable, timeout_unknown, and rejected states.
  - Tests required: provider error taxonomy tests and retry decision matrix tests.
- [x] 4.4 [P1] Add reconciliation jobs/worker design and operator controls.
  - Why it blocks live readiness: live state can drift outside request/response paths.
  - Acceptance criteria: reconciliation can be run on demand and scheduled; accounts with unresolved mismatch block new live orders.
  - Tests required: idempotent job tests, stale job lease tests, and account lockout tests.

## Phase 5: Live-Readiness Acknowledgements and Launch Gates

- [ ] 5.1 [P0] Add versioned live-readiness acknowledgement records scoped to user, account, integration, risk policy, and terms version.
  - Why it blocks live readiness: live access requires explicit, current, scoped acceptance of risk and responsibility.
  - Acceptance criteria: live enablement fails without a current acknowledgement; changes to risk settings, terms, account, or integration invalidate acknowledgement.
  - Tests required: acknowledgement CRUD, invalidation, expiry, cross-user isolation, and live-blocking tests.
- [ ] 5.2 [P0] Add launch gate API that reports pass/fail for all live-readiness criteria.
  - Why it blocks live readiness: live enablement must be controlled by objective gates, not hidden assumptions.
  - Acceptance criteria: gate covers context, risk policy, kill switch, account/equity freshness, order lifecycle, duplicate protection, reconciliation, migrations, acknowledgements, provider health, and UI readiness flags.
  - Tests required: gate matrix tests for each failing prerequisite and all-pass paper/demo state.
- [ ] 5.3 [P0] Keep live trading disabled unless launch gate explicitly passes and a separate allowlist/feature flag is enabled.
  - Why it blocks live readiness: implementation work must not accidentally enable live execution.
  - Acceptance criteria: live requests remain 403 until both gate and explicit live flag pass; default production and demo states block live.
  - Tests required: live-blocked default, missing flag, failing gate, expired acknowledgement, and allowlisted-gate-passing tests using fake adapter only.
- [ ] 5.4 [P1] Add frontend live acknowledgement flow and persistent risk disclosure surfaces.
  - Why it blocks live readiness: users must see and accept the actual risks before any controlled live access.
  - Acceptance criteria: UI shows no-profit guarantee, user responsibility, account/risk policy scope, expiration, and current blocker list.
  - Tests required: component tests for acknowledgement blocked, acknowledgement accepted, expired acknowledgement, and keyboard navigation.

## Phase 6: Accessibility, Responsive, and Operational Readiness

- [ ] 6.1 [P1] Add full dashboard readiness checklist covering provider, credentials, account, contract, market data, risk policy, kill switch, order lifecycle, reconciliation, acknowledgements, migrations, and mode.
  - Why it blocks live readiness: users need a complete visible safety model before trading actions are enabled.
  - Acceptance criteria: checklist is backed by API state and disables trading controls for any P0 blocker.
  - Tests required: frontend tests for each checklist blocker and backend readiness response tests.
- [ ] 6.2 [P1] Add responsive and accessibility tests for dashboard, integrations, auth, readiness checklist, live acknowledgement, and emergency stop controls.
  - Why it blocks live readiness: critical controls must be usable under real device and assistive technology conditions.
  - Acceptance criteria: Playwright or equivalent tests cover desktop, tablet, and mobile widths; keyboard access and accessible names exist for critical controls.
  - Tests required: responsive smoke tests, axe/accessibility checks if available, keyboard navigation tests, no-overlap screenshot checks.
- [ ] 6.3 [P0] Repair production migration baseline and add fresh-database migration verification.
  - Why it blocks live readiness: live deployment cannot rely on runtime `create_all()` or ambiguous schema history.
  - Acceptance criteria: a fresh database can be built from Alembic alone; `/health/ready` fails when DB revision is behind; migration rollback guidance exists.
  - Tests required: migration-up fresh DB test, schema constraint assertions, readiness-behind-head test.
- [ ] 6.4 [P1] Add operational runbook and support diagnostics for live-readiness incidents.
  - Why it blocks live readiness: support must investigate blocked orders, provider mismatches, risk lockouts, and reconciliation issues without exposing secrets.
  - Acceptance criteria: runbook covers disable live flag, activate kill switch, inspect audit, run reconciliation, restore from backup, and contact user.
  - Tests required: diagnostic API authorization tests and redaction tests.
