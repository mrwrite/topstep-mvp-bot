# Requirement Traceability

Status reflects the repository at assessment time, not task completion. `Partial` means some evidence exists but the new normative requirement is not fully satisfied. `Missing` means no adequate implementation evidence. `Blocked` means an unsafe current implementation or external prerequisite prevents beta use.

## P0 Implementation Checkpoint — 2026-07-26

This checkpoint supplements, but does not erase, the assessment-time matrix below.

| Requirement | New implementation evidence | New tests/evidence | Checkpoint status | Remaining gap |
| --- | --- | --- | --- | --- |
| Secure browser sessions | `auth_routes.py` issues bounded HttpOnly/SameSite cookies, stores CSRF hashes, rotates/revokes sessions, and implements logout; `frontend/src/api.ts` removes obsolete bearer storage | Cookie/CSRF/rotation/logout/expiry/revocation test; frontend API test | Partial | Managed session/key infrastructure, explicit fixation/XSS campaign, production evidence |
| Provider truthfulness | Central `ProviderDefinition`; API rejects unavailable credentials; UI consumes the same metadata; TopstepX hosted beta unavailable; TradingView signal-only | Backend provider-policy test and `Integrations.test.tsx` | Implemented for no-broker simulation scope | Commercial approvals and any broker adapter remain separate changes |
| Secret redaction | Nested/header/URL/query/JWT/bearer/exception redaction; legacy Topstep response/token printing removed; export allowlist | Structured-redaction and export-secret tests | Partial | Managed KMS rotation, backup/Sentry scan, credential rotation drill |
| Shared abuse control | Database-backed locked rate buckets with fail-closed 503 behavior | Distributed-state and legacy 429 tests | Partial | Dedicated-store benchmark, security alerts, durable bot leases |
| Account privacy lifecycle | Export allowlist; confirmed deletion; session revocation; credential erasure; honest provider-revocation outcomes; configurable grace/retention/hold | Export isolation and deletion/revocation tests | Partial | Provider-specific revocation, backup purge/restore drill, policy approval |
| Operator authorization | Central purpose/case/target dependency and append-only authorization audit | Operator denial/authorized-audit and existing non-admin tests | Partial | Role granularity, post-action outcome recording, incident drill |
| Migration reliability | Runtime `DATABASE_URL`, async-to-sync URL conversion, no local fallback, linear P0 migration | Empty PostgreSQL 17 upgrade reached `f8b9c0d1e2f3`; fresh SQLite test | Verified | Production upgrade/rollback rehearsal |
| Dependency and CI integrity | Exact Python lockfiles, npm lockfile, fixed production graph, required CI workflow | `pip check`; clean production npm audit; frontend build/tests | Partial | Clean-environment Python install/audit, protected CI run and branch rule |

| Requirement | Current implementation evidence | Current tests/evidence | Status | Remaining gap |
| --- | --- | --- | --- | --- |
| Secure account lifecycle | `app/auth_routes.py`; `EmailVerificationToken`, `PasswordResetToken`, `UserSession`; `Login.tsx`, `Register.tsx` | `test_paper_beta_phase1_account_lifecycle.py` | Partial | Explicit server logout, secure browser session design, distributed auth abuse controls, production email verification |
| Tenant isolation and operator authorization | User ownership filters across auth/integration/paper/risk/reconciliation routes; `is_admin` gates | Cross-user tests in auth, integration, phases 1-5, paper beta | Partial | Mandatory tenant repository/job context, purpose-bound operator roles and read audit |
| Account export and deletion | No account export/delete service or routes | None | Missing | Full export, revoke/stop/delete/retention receipt and backup behavior |
| Official least-privilege connection flow | Raw credential integration form; provider factory | Capability fail-closed tests | Blocked | OAuth/PKCE/minimum scopes; prevent credential collection for roadmap/unsupported providers |
| Verified account and environment | `TradingContextService`; integration metadata `environment`; account discovery for TopstepX | Context and provider capability tests | Partial | Provider-attested environment and immutable separation; reject client metadata claims |
| Credential lifecycle | Fernet blobs in `PlatformIntegration`; production key required | Encryption indirectly exercised | Blocked | KMS envelope rotation, provider revocation, non-redisplay, revoke-first disconnect, secret leak removal |
| Canonical adapter contract | `ProviderAdapter` supports health/accounts/contracts/order/status/positions/cancel/flatten skeleton | `test_phase2_integrations.py` | Partial | Auth refresh, instruments, historical/quotes/streaming, balances, preview/replace/events/reconciliation and typed conformance |
| Versioned capability discovery | Static implemented/roadmap maps in `providers/types.py` | Provider metadata tests | Partial | Environment/assets/order/event/rate/region/commercial manifest with evidence dates |
| Provider throttling and normalization | `ProviderError`; TradingView 429 retry; HTTP timeouts | TradingView retry tests | Partial | Per-provider budgets, headers, streaming throttles, unsafe retry separation, degraded health |
| Versioned configuration | `StrategyConfig` with version/name/parameters and bot session ID | Strategy phase tests | Partial | Draft/activation snapshots binding schedule/data/risk/environment and immutable hashes |
| Strategy validation and rationale | `strategy_engine.py`; parameter normalization; signal/guardrail/market snapshot | `test_phase4_strategy_engine.py` | Partial | Strict malicious-input schema, complete rationale, build/data/config identity |
| Market-session correctness | Poll interval and symbol only | None | Missing | Exchange calendars, timezone/DST/holiday/rollover and clock drift gates |
| Explicit simulation environment | Paper-only checks; `trading_mode`; health/ops; UI banners | Safety, execution, strategy, demo, production-readiness tests | Partial | Provider-attested environment, separate grants/credentials/config/data and no promotion |
| Truthful execution model | Paper ledger and assumptions explicitly omit costs | Paper execution/demo tests | Partial | Spread/slippage/fees/margin/liquidity/session/expiry models and itemized reports |
| Reproducible backtests | `app/backtesting.py` basic deterministic loop and assumptions | `test_backtesting.py` | Partial | Data/config/build fingerprints, no-look-ahead tests, survivorship disclosure, out-of-sample/walk-forward |
| Live trading default-deny | `assert_live_trading_blocked`; context/service gates; `live_trading_enabled: false` | Multiple live-rejection and provider-spy tests | Fully functional and verified for current no-live boundary | Preserve; later live requires separate approved implementation |
| Explicit activation ceremony | `LiveReadinessAcknowledgement` and launch-gate evidence | `test_live_readiness_phase5_launch_gate.py` | Partial | Reauth, provider-verified live account, typed confirmation, short-lived server grant; live remains disabled |
| Activation revocation and drift | Acknowledgement expiry/invalidation fields | Launch-gate tests | Partial | Grant revocation triggers and runtime drift enforcement |
| Server-side pre-trade risk | `risk_service.evaluate_order`; called by paper execution | Risk and ledger tests | Partial | Transactional current broker state, reservations, pending exposure, full connectivity/session inputs |
| Required risk limits | Quantity, contracts, daily loss, open positions, live flag, daily state | `test_live_readiness_phase2_risk.py` | Partial | Notional/portfolio/symbol exposure, trade count, consecutive losses, trusted resets |
| Emergency controls | Durable scoped `KillSwitch`; risk gate; dashboard control | Risk, launch-gate, demo tests | Partial | Shared-worker latency, cancel/flatten semantics, provider confirmation, global incident scope |
| Idempotent order intent | Unique `(user_id,idempotency_key)`; fingerprint window | `test_phase3_paper_execution.py`, ledger tests | Partial | Environment/account/client ID scope, durable worker/outbox, unknown provider outcome before retry |
| Complete lifecycle and fill accounting | Paper order/event/fill/position/account/ledger tables | Paper lifecycle/ledger/reconciliation tests | Partial | Real provider accepted/rejected/partial/cancel/replace/expiry/unknown events and projections |
| Deterministic reconciliation | Reconciliation runs/events/retry decisions/account locks | `test_live_readiness_phase4_reconciliation.py` | Partial | Automatic startup/reconnect/gap/interval broker snapshots and deterministic repair/manual workflow |
| End-to-end decision trace | Strategy signal snapshot, risk decision, order events/fills/ledger | Strategy, risk, execution tests | Partial | Append-only causal trace from source data through P&L and user drill-down |
| Tamper evidence and redaction | JSON log events and key-name redactor | Analytics/support redaction tests | Blocked | Raw token/response logging removal, message/exception redaction, integrity protection, operator-read audit |
| User-understandable explanations | Stable risk/blocker codes, signal reasons, order statuses, UI messages | Risk/launch/strategy tests | Partial | Unified taxonomy and full submitted/accepted/filled provider distinction |
| Safety and reliability telemetry | `/health/*`, `/ops/status`, request IDs, local analytics | `test_phase6_production_readiness.py`, analytics tests | Partial | Market/event/clock/worker/order/reconciliation/kill/notification metrics and external alerting |
| User-visible operational states | Readiness blocker and error UI | Frontend static smoke | Partial | Durable healthy/degraded/paused/reconciling/incident states with last-good time |
| Actionable notifications | Email verification/reset; support notification fields | Account lifecycle and support tests | Partial | Broker/order/risk/reconciliation/incident notifications, dedupe and delivery status |
| Secret protection | Fernet credential encryption; config checks; key-name redactor | Production config and analytics redaction tests | Blocked | `app/auth.py` prints tokens/responses; KMS rotation; exception/trace/export/backup redaction |
| Security controls and dependency hygiene | Baseline headers/CORS/rate limiter; `.gitignore` excludes env/logs | `pip check`; `npm audit` result; safety tests | Blocked | Seven npm advisories, unpinned Python, no CI/SAST/secret scanning, distributed abuse controls |
| Privacy lifecycle and backups | Deployment notes recommend managed backup; placeholder privacy doc | Documentation only | Missing | Reviewed policy, export/delete, retention, cryptographic erasure, tested restore |
| Staged release gates | Live launch gate; invite/legal/onboarding/entitlements | Phase 5 launch tests and paper-beta tests | Partial | Simulation/broker-paper stage gates, cohort caps, automated critical veto, beta gate tasks 7.1-7.6 |
| Controlled cohorts and support | Invite/waitlist/beta status/support routes | Paper beta phase 3/4 tests | Partial | Named owner/hours/SLA, caps, incident thresholds, documents, risk acceptance |
| Incident containment and rollback | Kill/stop routes and operational runbook | Risk tests; docs | Partial | Durable global/provider pause, worker controls, notifications, backup/rollback/reconcile game day |
| Honest product and legal communication | Paper/live disclaimers; legal acceptance tables; placeholder terms/privacy | Legal and demo tests | Blocked | README/UI provider overclaims, unsupported TradingView data API claim, counsel-reviewed documents and pricing/support scope |

## Current Evidence Index

| Area | Primary implementation | Primary tests |
| --- | --- | --- |
| Identity/session | `app/auth_routes.py`, `app/security.py`, `app/models.py` | `tests/test_auth_integrations.py`, `tests/test_paper_beta_phase1_account_lifecycle.py` |
| Legal/invite/onboarding/support | `legal_*`, `beta_access_*`, `onboarding_*` | `test_paper_beta_phase2_*` through `phase4_*` |
| Analytics/entitlement | `analytics_*`, `subscription_*` | `test_paper_beta_phase5_*`, `phase6_*` |
| Connections/adapters | `integrations_*`, `providers/*`, `trading_context.py` | `test_phase2_integrations.py`, `test_live_readiness_phase1_context.py` |
| Paper execution | `paper_execution.py`, `trading_safety.py`, `scheduler.py` | `test_phase1_safety.py`, `test_phase3_paper_execution.py`, `test_live_readiness_phase3_ledger.py` |
| Strategy/backtest | `strategy.py`, `strategy_engine.py`, `backtesting.py` | `test_phase4_strategy_engine.py`, `test_backtesting.py` |
| Risk/kill | `risk_service.py`, `risk_routes.py` | `test_live_readiness_phase2_risk.py` |
| Reconciliation/launch | `reconciliation_*`, `launch_gate_*` | `test_live_readiness_phase4_reconciliation.py`, `phase5_launch_gate.py` |
| Demo/operations | `demo.py`, `health.py`, `observability.py` | `test_phase6_production_readiness.py`, `test_phase7_demo_package.py` |
| Frontend | `frontend/src/pages/*`, `frontend/src/api.ts` | `scripts/phase6_frontend_readiness_smoke.py`; production build |

## Verification Commands for Future Implementation

Every implementation phase must keep the current safety suite and add requirement-specific tests. The minimum local/CI command set is:

```powershell
venv\Scripts\python.exe -m pytest -p no:cacheprovider
venv\Scripts\python.exe scripts\demo_smoke.py
venv\Scripts\python.exe scripts\phase6_frontend_readiness_smoke.py
venv\Scripts\python.exe -m pip check
venv\Scripts\python.exe -m compileall -q app tests scripts
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m alembic current
npm.cmd audit --omit=dev
npm.cmd run build
cmd /c openspec validate audit-and-prepare-multi-broker-beta-readiness --strict --no-interactive
git -c safe.directory=C:/Users/aquin/source/repos/topstep_mvp_bot diff --check
```

Provider-paper phases additionally require adapter conformance, replay/duplicate, partial-fill, rejection, cancel/replace, rate-limit, token-expiry, disconnect, restart, network-partition, and broker/local drift commands recorded in CI and the release evidence bundle.
