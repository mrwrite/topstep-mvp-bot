# Multi-Broker Beta Readiness Report

Assessment date: 2026-07-26  
Change: `audit-and-prepare-multi-broker-beta-readiness`  
Scope: repository evidence, local runtime/tests, current official provider/product documentation  
Legal note: this report identifies areas requiring qualified legal and compliance review; it is not legal advice.

## P0 Implementation Checkpoint — 2026-07-26

The first remediation pass removed raw Topstep credential/token logging, introduced centralized structured redaction, moved browser authentication to HttpOnly cookie sessions with CSRF protection, moved request rate limits to shared database state, made provider credential availability fail closed, added purpose-bound operator audit records, added account export/deletion records, repaired runtime-configured migrations and demo smoke, removed the seven original production npm advisories, and added CI definitions.

This checkpoint does **not** change the release recommendation to GO. Invite-only simulation beta remains **NO-GO** until every beta-blocker task has its stated completion evidence. Managed KMS/vault selection and rotation, mandatory tenant context across jobs/repositories, durable bot runs/leases, protected CI evidence, clean-environment lock verification, complete operator action outcomes, backup/restore/deletion drills, warning-budget enforcement, and owner-approved legal/retention/support policy remain incomplete. Live-money beta remains prohibited and server-side live rejection is unchanged.

## Executive Release Recommendation

**Overall readiness: 1.7/5 (34/100), external beta no-go.** The numeric average is informational only. Critical secret leakage, vulnerable production dependencies, incomplete operator/tenant controls, non-durable execution, unverified provider authorization, inaccurate provider/data claims, broken documented smoke/migration workflows, and incomplete order/reconciliation behavior independently block external release.

| Stage | Recommendation | Basis |
| --- | --- | --- |
| Internal verification | **GO, paper-only** | Live requests are server-blocked; 113 tests pass; demo and paper functionality have useful coverage. Use only fake/demo credentials and treat logs as sensitive until secret logging is removed. |
| Invite-only simulated beta | **NO-GO now; conditional next stage** | Reasonable first external target after P0 security, dependency, migration/smoke, tenant/operator, support, and release-gate work is complete. |
| Invite-only broker paper-account beta | **NO-GO** | No production-quality external paper adapter exists; current TopstepX adapter is contractually unsuitable for hosted beta; execution/reconciliation and credential lifecycle are incomplete. |
| Live-money beta | **NO-GO** | Live is intentionally disabled and lacks approved providers, activation grants, lifecycle events, deterministic reconciliation, complete risk controls, staffed operations, reviewed legal terms, and recovery evidence. |

The proposed first external beta is invite-only local simulation. The next stage is a small Tradovate demo and/or Alpaca paper cohort only after adapter conformance and all critical gates pass. No stage may silently promote paper state to live.

## Current Capability Inventory

### Verifiably functional

- FastAPI account registration and bcrypt password hashing (`app/auth_routes.py`, `app/security.py`).
- Email verification, password reset, persisted sessions/revocation, recovery requests, profile fields, and readiness gates, covered by `tests/test_paper_beta_phase1_account_lifecycle.py`.
- User-scoped integration CRUD with Fernet-encrypted credential blobs (`app/integrations_routes.py`, `app/crypto.py`, `models.PlatformIntegration`).
- Capability tables that distinguish implemented versus roadmap provider features (`app/providers/types.py`), although the UI still permits misleading setup.
- Explicit paper-only guards in `app/trading_safety.py`, `app/trading_context.py`, `app/scheduler.py`, and strategy creation.
- Durable user-scoped paper order/event/fill/position/account/ledger records with a unique `(user_id, idempotency_key)` index.
- Immediate local market-order simulation with duplicate fingerprint checks and user-scoped reads (`app/paper_execution.py`).
- `rsi-threshold-v1` configuration, RSI signal records, minimum-bar/stale-bar suppression, cooldown/signal-rate guardrails, and paper metrics (`app/strategy_engine.py`).
- Server-side risk settings for quantity, contracts, daily loss, open positions, paper/live flag, and daily lock; scoped kill-switch and risk-decision records (`app/risk_service.py`).
- Reconciliation run/event/retry/lock schemas and diagnostic APIs; tests cover classification and lock behavior.
- Launch-gate evaluation and acknowledgement evidence that still reports live unavailable.
- Invite/legal/onboarding/support/analytics/entitlement structures and routes; the active `paper-beta-readiness` change has 30/36 tasks marked complete.
- User-scoped fake TopstepX demo seed/reset with two simulated fills, positions, strategy signal, and no broker call (`app/demo.py`).
- Health/readiness/ops endpoints, structured JSON logging, request IDs, baseline headers, CORS validation, and basic in-memory rate limiting.
- React login/register/integration/dashboard experience with paper/live copy, risk readiness, kill switch, paper positions/orders/P&L, strategy signals, support, onboarding, legal, beta, subscription, and demo surfaces.

### Partial, unsafe, or unsupported

- `TopStepXAdapter` has login, account, contract, historical bars, and a basic market `place_order`, but no production streaming order/fill lifecycle, cancel/replace implementation, position/balance reconciliation, capability-depth model, token revocation, or hosted-use authorization.
- Tradovate, NinjaTrader, IBKR, and ETX adapters are placeholders with empty implemented capabilities.
- TradingView webhook signals are a plausible signal source, but `app/tradingview_api.py` and docs assume a general `api.tradingview.com` data API that TradingView officially says is not available to retail consumers. The official REST API is for brokers integrating into TradingView; webhooks are the supported outbound mechanism.
- Paper execution immediately fills market orders at a reference price. It does not model commission, spread, slippage, liquidity, margin, sessions, contract expiry, or partial fills.
- Backtests operate on a single data interval with no fees/slippage/margin/liquidity, no data/version fingerprint, no out-of-sample or walk-forward workflow, and unresolved look-ahead/survivorship validation.
- Bot sessions and request-rate buckets are process memory, so restart and multi-worker semantics are unsafe.
- Reconciliation structures exist, but no live provider event stream and full authoritative broker-state convergence path is implemented.
- Legal and privacy documents are explicitly placeholders.
- No account data export or account deletion workflow exists.
- No verified deployment pipeline, container/build manifest, protected CI configuration, monitored production environment, or tested rollback is present.

## Critical User Journey Results

Status vocabulary: **Fully functional and verified**, **Partially functional**, **Present but unverified**, **Missing**, **Unsafe for beta**.

| # | Journey | Status | Evidence and remaining gap |
| --- | --- | --- | --- |
| 1 | Visitor signs up | Partially functional | `POST /auth/register`, `Register.tsx`, and auth tests work. Registration is public and the invite gate occurs later; distributed abuse controls/CAPTCHA and production email delivery are unverified. |
| 2 | Verify identity/email | Fully functional and verified for email | Hashed, expiring, single-use verification records and tests exist. No KYC/identity verification is claimed or required for simulation; broker KYC remains provider-owned. |
| 3 | Sign in/out/reset/manage sessions | Partially functional | Login, reset, list/revoke sessions are tested. UI “logout” removes `localStorage` token rather than reliably revoking the server session; no explicit current-session logout route; bearer token in `localStorage` increases XSS impact. |
| 4 | Connect supported paper/sandbox broker securely | Unsafe for beta | Credential CRUD exists, but no external broker-paper adapter is production-ready. Roadmap providers can collect credentials; TopstepX has no sandbox and hosted-use restrictions. |
| 5 | Grant minimum permissions | Missing | No OAuth/PKCE least-scope flow or scope verification. The current UI accepts raw credentials/tokens. |
| 6 | Select instruments/session rules | Partially functional | Account/contracts/symbol are selected and context-validated in covered paths. No authoritative instrument metadata, exchange calendar, timezone/DST/holiday, rollover, or session rule model. |
| 7 | Select/configure strategy | Partially functional | Versioned `rsi-threshold-v1`, thresholds, cooldown, max signals, bar/stale guardrails exist. No draft/activation lifecycle, immutable snapshot hash, or schedule/risk binding. |
| 8 | Configure risk limits | Partially functional | Quantity, contracts, daily loss, open positions, kill switch exist and tests pass. Missing notional/portfolio exposure, trade count, consecutive losses, transactional reservations, and full cancel/flatten policy. |
| 9 | Validate before enabling | Partially functional | `TradingContextService`, risk checks, beta/legal/entitlement/onboarding gates, and launch gate exist. Provider/account environment and full capabilities are not verified; bot state remains in process. |
| 10 | Run simulation/paper session | Fully functional and verified for local simplistic paper | Manual and strategy paper orders, demo, ledger, positions, metrics, and no-live tests pass. Execution realism is insufficient for performance conclusions. |
| 11 | Review rationale/signals/orders/fills/performance | Partially functional | Strategy snapshots/reasons, risk decisions, paper lifecycle, fills, positions, and P&L surfaces exist. No end-to-end immutable trace; fees/slippage absent; accepted/submitted versus fill semantics are only robust in local immediate-fill path. |
| 12 | Start/pause/resume/stop | Partially functional | Create/start and stop are present; pause/resume are not durable first-class commands. `BOT_SESSIONS` is process memory and cannot safely recover or coordinate workers. |
| 13 | Emergency kill switch | Fully functional and verified for blocking paper entries | Server-side scoped switch and regression tests exist. Immediate multi-worker propagation, cancel-working-orders, flatten, global incident mode, and latency objectives are missing. |
| 14 | Recover from failures/conflicts | Partially functional | Idempotency, stale-data suppression, retry classifications, reconciliation locks, and tests exist. No real provider partial-fill/event stream, durable worker leases, startup reconciliation, network partition/DB outage game day, or deterministic live recovery. |
| 15 | Disconnect/revoke broker | Unsafe for beta | `DELETE /integrations/{id}` removes the local row. It does not guarantee provider token revocation, stop all runs, reconcile state, or preserve a disconnect receipt. |
| 16 | Delete/export account data | Missing | No route, schema workflow, retention policy, or backup deletion behavior. |
| 17 | Operator investigates safely | Unsafe for beta | Admin gates exist for beta/support/analytics/subscriptions, and structured logging redacts named keys. There is no purpose-bound operator audit; legacy auth prints Topstep tokens; exception text can expose secrets; cross-user operator views lack a unified security model. |

## Platform Integration Viability

Facts below come from current official documentation and were checked on the assessment date. “Not publicly verified” means this assessment did not find an authoritative published value and implementation must discover it during provider onboarding rather than invent one.

| Platform | Assets / official API | Paper or sandbox | Auth, data, orders, events, limits | Restrictions and credential needs | Tier / disposition |
| --- | --- | --- | --- | --- | --- |
| Tradovate | Futures; official REST plus WebSocket services, accounts/contracts/orders/positions | Production demo simulation endpoints are documented | OAuth and bearer tokens; separate live/demo and market-data domains; user/market streams; order lifecycle APIs. Exact applicable rate budget requires partner confirmation. | Client ID/secret and partner/application approval; device identity; market-data rights; use delegated auth and encrypted refresh tokens. | **Tier 1 broker-paper candidate**. Best futures sandbox fit and close to current domain. |
| Alpaca | US equities, options, and crypto through official Trading/Broker/Data APIs | Separate paper domain and credentials | Key auth for direct accounts; OAuth/Broker flows for third parties; REST and WebSocket trade/data updates; published direct trading limit is 200 requests/min/account, while Broker API limits are partner-specific. | Partner/commercial and regional eligibility review; market-data plan differences; strict paper/live domain and key separation. | **Tier 1 broker-paper candidate**. Strong environment separation and automation-first API. |
| NinjaTrader | Primarily futures; official REST Trade API and WebSocket Market Data API | Demo/simulation endpoints exist in the Tradovate/NinjaTrader platform ecosystem | OAuth/bearer, account/order/position/risk REST, real-time market data and user events. Exact access/rates require provider agreement. | Commercial developer access and overlap with Tradovate must be clarified; do not treat the local placeholder as supported. | **Tier 2** after Tradovate; avoid duplicate integration effort until terms/capabilities justify it. |
| IBKR | Global equities, options, futures, futures options, forex, and more; Web API/TWS API | Paper account with documented simulator limitations | OAuth 1.0a/2.0, SSO, or local gateway depending relationship; REST/WebSocket; broad order/account/data support; pacing and session constraints. | Third-party vendors need compliance approval; currently OAuth 1.0a approval path is documented; live account must be open/funded IBKR Pro for Web API; market-data subscriptions; Canadian API trading restrictions for Canadian products. | **Tier 2**. Powerful but operationally and contractually heavier. |
| OANDA v20 | Forex/CFD by region; official REST v20 | Practice environment | Personal access token/delegated arrangements, REST plus price/transaction streams, orders/accounts/positions; official comparison documents 20 aggregate streams and polling-rate constraints. | Regional instrument/product restrictions, CFD eligibility, market hours, and partner terms require review. | **Tier 2** for a later region-limited forex cohort. |
| Coinbase Advanced | Crypto spot and region-dependent derivatives; official REST/WebSocket | Advanced Trade sandbox is static/mock responses, not realistic forward paper; Exchange sandbox is a separate institutional-style environment | CDP API keys/JWT or OAuth portfolio access; public/user WebSocket; preview/create/cancel/edit and events. Rate details vary by API. | Private signing keys need vault custody; portfolio scopes and geographic product eligibility; static retail sandbox limits validation. | **Tier 3** until a realistic authorized paper path exists. |
| TopstepX / ProjectX | Futures; official REST and WebSocket API; repository has partial REST adapter | Official help says no sandbox | Username plus generated API key yields bearer session; accounts, contracts, history, orders/cancel/modify, positions and trades documented; API subscription required. | Official help prohibits VPS, VPN, and remote-server-originated activity; all activity must originate from the personal device. ProjectX API automation is prohibited for Live Funded Accounts. No sandbox. | **Tier 3 for a local-agent design; unsupported for this hosted external beta.** Preserve adapter only behind explicit restrictions and fake/local simulation. |
| TradingView | Charting/alerts and broker integrations; not a retail broker API | TradingView paper exists in its product, but no general consumer market-data REST API for this bot | Supported outbound webhook alerts; HTTPS, 3-second receiver timeout, ports 80/443, delivery may fail; webhook certificate/IP verification options. | TradingView states it does not offer an API for consumer data/indicator access; its REST API is for brokers integrating into TradingView. Market-data licenses are separate. | **Tier 1 signal source only** after authenticated replay-safe webhook work. The repository data wrapper is **unsupported** unless a separate licensed contract is produced. |
| Browser-only/unofficial platforms | Varies | Varies | No suitable official authorized automation contract | Would require browser automation, credential scraping, reverse-engineered endpoints, or unsafe password custody. | **Unsupported**. |

Official evidence:

- [TopstepX API access and restrictions](https://help.topstep.com/en/articles/11187768-topstepx-api-access)
- [Topstep Live Funded Account parameters](https://help.topstep.com/en/articles/10657969-live-funded-account-parameters)
- [TopstepX Swagger](https://api.topstepx.com/swagger/index.html)
- [Tradovate API](https://api.tradovate.com/)
- [NinjaTrader developer API overview](https://docs.ninjatrader.com/)
- [Alpaca trading rate limit](https://alpaca.markets/support/usage-limit-api-calls)
- [Alpaca Broker API rate limits](https://docs.alpaca.markets/us/docs/broker-api-rate-limits)
- [IBKR Web API access and third-party approval](https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-doc/)
- [IBKR paper limitations](https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/)
- [OANDA API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)
- [Coinbase Advanced Trade sandbox](https://docs.cdp.coinbase.com/coinbase-business/advanced-trade-apis/sandbox)
- [Coinbase WebSocket overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-overview)
- [TradingView consumer API statement](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/)
- [TradingView webhook behavior](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)

## Competitive Capability Matrix

This matrix compares documented capabilities, not profitability. `Yes` means the cited public documentation clearly describes the capability; `Partial` means it is limited or model-dependent; `Unverified` means the reviewed official public sources did not establish it.

| Capability | This bot now | TradersPost | QuantConnect | Capitalise.ai | Trade Ideas |
| --- | --- | --- | --- | --- | --- |
| Guided onboarding | Partial | Yes | Partial/technical | Yes | Partial/desktop |
| Multiple brokers/markets | Roadmap claims; one partial adapter | Yes | Yes | Partner-dependent | Limited participating brokers |
| Paper trading | Yes, simplistic local | Yes, broker and basic local | Yes, multi-asset paper | Yes, simulation | Yes, simulator/broker simulator |
| Strategy configuration | One RSI strategy | Webhook/subscription configuration | Code/algorithm framework | No-code natural language | Scanner/strategy tooling |
| Backtesting | Basic | External strategy source oriented | Strong | Yes | Yes |
| Walk-forward/out-of-sample | No | Unverified | Walk-forward documented | Unverified | Unverified |
| Fees/slippage/spread models | No | Paper limitations disclosed | Configurable models; defaults vary | Unverified | Unverified |
| Decision explainability | Partial signal reasons | Signal/order routing views; no broker feedback loop disclosed | Code/log/result driven | Strategy monitoring | Strategy/alert driven |
| Risk controls | Partial server controls | Position sizing and settings; documented limitations | Programmable brokerage/risk models | Strategy controls | Brokerage Plus controls |
| Kill switch | Paper entry block | Monitoring/user control; exact server SLA unverified | Stop algorithm/liquidate programmable | Stop/manage strategies | Automation controls |
| Broker-state feedback/reconciliation | Structures only | Explicitly documents no broker-state/order feedback loop for strategy logic | Brokerage event model | Unverified | Broker-dependent |
| Audit/trace | Partial records | Signal/subscription logs | Backtest/live results and orders | Monitoring/history | Strategy/order history |
| Notifications | Basic support/status | Platform notifications | Configurable notifications | Mobile alerts documented | Alerts |
| Mobile responsiveness | Partial/manual checklist | Cloud web | Web platform | Mobile app documented | Desktop-centric |
| Data export | Missing account export | Unverified | Backtest JSON/CSV results | Personal data controls exist; format unverified | Unverified |
| Security documentation | Sparse | Connection/control statements | IP/data access statements | Account/integration controls | Unverified |
| Documentation/support | Basic local docs | Extensive docs/support | Extensive docs/community | Help center | User guide/support |
| Pricing transparency | Billing disabled, no public product plan | Public product site not verified in this review | Public commercial model; exact current plan table not captured | Current availability/pricing requires owner verification | Public pricing exists but exact current table not captured |
| Performance-claim transparency | Disclaimers present | Paper limitations and monitoring warnings explicit | Past-performance disclaimer and model assumptions | Backtest/simulation framing | Simulator-first recommendation |

Sources:

- [TradersPost overview and explicit limitations](https://docs.traderspost.io/docs)
- [TradersPost paper trading assumptions](https://docs.traderspost.io/docs/learn/platform-concepts/paper-trading)
- [QuantConnect paper trading](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/quantconnect-paper-trading)
- [QuantConnect walk-forward optimization](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization)
- [QuantConnect slippage modeling](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts)
- [Capitalise.ai Help Center](https://support.capitalise.ai/en)
- [Trade Ideas simulator](https://www.trade-ideas.com/ti-papertrading/)

The standards to meet or exceed are therefore measurable:

- 100% trace coverage from input to fill for sampled and incident orders.
- Zero duplicate effective orders in retry, restart, partition, and multi-worker fault tests.
- Deterministic reconciliation fixtures for every supported provider lifecycle state.
- Server-enforced daily loss, position, exposure, order size, trade count, consecutive loss, stale-data, connectivity, and kill-switch gates.
- Median kill-switch entry-block propagation under the owner-approved SLA, measured from durable activation to worker enforcement.
- Physically and logically separate paper/live grants, credentials, configuration versions, data, metrics, and indicators.
- No live activation without provider/account verification, reauthentication, typed confirmation, versioned consent, recent readiness evidence, and a server grant.
- Performance reports that itemize fees, spread, slippage, data range, assumptions, and limitations.
- Reproducible backtests with data/config/build fingerprints and explicit look-ahead/survivorship controls.
- Degraded state visible within the owner-approved detection interval and unsafe states failing closed.
- Zero plaintext secrets in seeded log/error/analytics/support/export/backup scans.
- Successful backup, restore, incident, and rollback game days before each stage expansion.

## Security and Threat Findings

| Threat/finding | Severity | Likelihood | Impact | Mitigation | Detection | Release disposition |
| --- | --- | --- | --- | --- | --- | --- |
| Legacy Topstep auth prints full response and session token (`app/auth.py`) | Critical | High when fallback used | Broker account takeover and unauthorized orders | Remove secret output, rotate exposed keys/tokens, prohibit legacy helper, add allowlist logging | Seeded-token log scan; secret scanner | **Blocks any external beta** |
| Exception and provider error strings can bypass key-based redaction | Critical | Medium | Credentials/provider payload leak to logs/Sentry/support | Redact message/exception text, structured allowlists, never log raw upstream bodies | Canary-secret integration tests | **Blocks external beta** |
| Browser bearer token in `localStorage` | High | Medium | XSS becomes session takeover | HttpOnly/SameSite secure session design, CSP, CSRF protection, rotation | Security tests, CSP reports, session anomaly alerts | Blocks external beta pending threat review |
| Public registration and in-memory IP/path rate limiter | High | High | Abuse, spam, brute force, memory exhaustion, easy multi-instance bypass | Invite-first admission, distributed limits, device/email controls, alerting | Auth rate/abuse metrics | Blocks invite beta |
| Route-level ownership conventions without mandatory tenant repository context | Critical | Medium | Cross-user trading/data access | Tenant context, database constraints/RLS evaluation, two-tenant tests for jobs/admin/exports | Authorization audit and test matrix | Blocks external beta |
| Operator/admin reads lack unified purpose-bound audit | High | Medium | Insider or accidental cross-user exposure | RBAC, case/purpose, least privilege, audited reads, break-glass policy | Immutable operator-access events | Blocks external beta |
| Roadmap providers accept credentials before capability/approval | Critical | High | Secret collection without usable/authorized integration | Do not collect for unavailable providers; OAuth and evidence-dated status | UI/API negative tests | Blocks external beta |
| Local integration delete does not guarantee provider revocation | High | Medium | Orphaned active grants and continued access | Revoke-first disconnect saga, stop/reconcile, receipt | Revocation health checks | Blocks broker beta |
| Dev encryption derives credential key from JWT secret; no rotation workflow | High | Medium | Coupled compromise and undecryptable/unchanged ciphertext on rotation | Managed KMS envelope encryption and tested rotation | Key-version inventory and drills | Blocks real credentials |
| Replay/duplicate orders after unknown provider outcome | Critical | Medium | Excess position/loss | Durable client IDs, unknown state, reconciliation-before-retry, account lock | Duplicate fingerprints, unknown-order alerts | Blocks broker/live beta |
| In-process `BOT_SESSIONS` and rate state | Critical for live | High on restart/scale | Lost control state, duplicate workers, bypassed limits | Durable runs, leases, outbox, shared limiter | Lease conflict/restart fault tests | Blocks broker/live beta |
| Race between concurrent risk checks | Critical for live | Medium | Limits exceeded despite individual approval | Transactional risk reservations and serializable scope locking | Concurrency tests/metrics | Blocks broker/live beta |
| Stale/missing market data | High | Medium | Invalid signals/orders | Trusted timestamps, sequence/gap checks, stale circuit breaker | Quote-age and gap alerts | Current strategy has partial guard; blocks broker beta until end-to-end |
| Clock drift/session/DST/holiday error | High | Medium | Trading closed/wrong contract/session | NTP monitoring, exchange calendars, provider instrument sessions | Clock-offset and session-gate alerts | Blocks broker/live beta |
| Partial fill/rejection/cancel replacement mishandling | Critical | High once external | Wrong position, duplicate exits, false P&L | Full state machine and cumulative-fill accounting | Lifecycle conformance tests | Blocks broker/live beta |
| Broker/local position drift | Critical | Medium | Unbounded exposure and wrong risk state | Startup/continuous reconciliation and account locks | Drift metrics and alerts | Blocks broker/live beta |
| Network partition/broker outage | Critical | Medium | Unknown orders, unmanaged positions | Fail closed, durable cursors, unknown state, reconciliation | Connectivity/event-lag alerts | Blocks broker/live beta |
| Database outage or restore | Critical | Medium | Lost intent/audit state, duplicates after recovery | Transactional writes/outbox, backups, restore/reconcile gate | DB health, restore drills | Blocks broker/live beta |
| Worker duplication | Critical | Medium | Duplicate orders | Leases, fencing tokens, idempotent consumers | Lease and duplicate metrics | Blocks broker/live beta |
| Excessive loss/runaway submissions | Critical | Medium | Financial loss | Multi-dimensional limits, trade-rate circuits, kill switch, broker limits | Risk rejection and order-rate alerts | Blocks live beta |
| Unsupported instrument/order type | High | High with multiple providers | Rejection or unintended order semantics | Capability/instrument preflight | Configuration rejection metrics | Blocks broker beta |
| Paper/live confusion | Critical | Medium | Real-money order believed simulated | Provider-verified environment, separate credentials/data/grants, persistent UI | Environment mismatch alerts | Live remains blocked; blocks any future live |
| Malicious strategy configuration | High | Medium | Resource abuse or unsafe orders | Fixed strategy schemas, size/range validation, no user code | Validation and anomaly metrics | Blocks external beta until limits added |
| Dependency/supply-chain advisories | High | High/current | XSS, request/credential manipulation, DoS | Upgrade, lock, scan, protected CI, provenance | `npm audit`, SCA, lock diff review | **Current seven-advisory result blocks external beta** |
| Missing complete audit evidence | High | High | Cannot explain incidents/disputes | Append-only trace and correlation IDs | Trace completeness metric | Blocks broker/live beta |

## Risk and Failure-Mode Analysis

The safe invariant is: **when state is unknown, do not create new exposure**. A submitted order is not a fill; an HTTP timeout is not a rejection; a reconnect is not recovery; and a local position is not authoritative without broker evidence.

| Failure | Required deterministic response | Recovery evidence |
| --- | --- | --- |
| Duplicate command or webhook | Return original result if identical; reject conflict; never create second effective intent | Unique key and event fingerprint |
| Submission timeout | Mark unknown, lock entries, query by client/provider identity | Reconciliation run links found/not-found evidence |
| Stale/missing bars or quote | Suppress signal and block entry | Fresh timestamp/sequence and readiness recheck |
| Partial fill | Post only cumulative fill delta; maintain remaining quantity | Provider event sequence and position projection |
| Rejection | Preserve reason and release risk reservation | Final provider rejection event |
| Cancel races with fill | Accept provider event ordering; final position derives from fills | Cumulative fills plus broker open-order snapshot |
| Restart | Acquire fenced lease, restore checkpoint, reconcile before evaluating | Lease token, checkpoint, reconciliation pass |
| Network partition | Pause new entries; preserve working-order uncertainty | Restored stream/REST health and broker snapshot |
| Broker outage | Provider circuit open; user-visible degraded state | Provider health plus reconciliation |
| Database outage | Stop submissions if intent/audit cannot commit | DB recovery, outbox consistency, reconciliation |
| Position drift | Account lock, preserve both views, deterministic or manual resolution | Signed resolution event and matching snapshot |
| Kill switch | Durable block first; cancel/flatten only by explicit provider-aware policy | Measured enforcement, broker order/position confirmation |

## Test and Runtime Evidence

Commands were run from `C:\Users\aquin\source\repos\topstep_mvp_bot` on Windows/Python 3.12.10/Node 20.19.4 unless noted.

| Command | Result |
| --- | --- |
| `venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp="$env:TEMP\topstep-beta-audit-pytest"` | **TIMEOUT** after 120.4s at 41%; 113 collected and no failure had appeared. |
| `venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp=".tmp\audit-pytest-full"` | **PASS**: 113 passed in 313.48s; 4,455 warnings. |
| `venv\Scripts\python.exe scripts\demo_smoke.py` | **FAIL** in 2.5s: `ModuleNotFoundError: No module named 'app'`. |
| `$env:PYTHONPATH='.'; venv\Scripts\python.exe scripts\demo_smoke.py` | **FAIL** in 6.1s: `sqlite3.OperationalError: no such table: users`; registration returned 500. |
| `venv\Scripts\python.exe scripts\phase6_frontend_readiness_smoke.py` | **PASS**. |
| `npm.cmd run build -- --outDir "$env:TEMP\topstep-beta-audit-frontend-dist" --emptyOutDir` | **UNAVAILABLE due environment**: Node `EPERM` resolving `C:\Users\aquin` outside permitted workspace. |
| `npm.cmd run build -- --outDir ..\.tmp\audit-frontend-dist --emptyOutDir` | **PASS**: Vite transformed 88 modules and built in 3.45s; 257.51 kB JS and 11.51 kB CSS. |
| `venv\Scripts\python.exe -m pip check` | **PASS**: no broken requirements. This is not a vulnerability scan and Python requirements are unpinned. |
| `venv\Scripts\python.exe -m compileall -q app tests scripts` | **PASS**. |
| `npm.cmd audit --omit=dev --json` | **FAIL / release blocker**: 7 production vulnerabilities: 6 high, 1 moderate; direct affected packages include axios and react-router-dom; fixes reported available. |
| `venv\Scripts\python.exe -m alembic current` | **FAIL**: local PostgreSQL at `localhost:5432` unavailable; `alembic.ini` uses a hardcoded URL. |
| `venv\Scripts\python.exe -m alembic heads` | **PASS**: one head, `f7a8b9c0d1e2`. |
| `venv\Scripts\python.exe -m alembic history` | **PASS**: linear history from base through `f7a8b9c0d1e2`. |
| Set temporary `DATABASE_URL=sqlite:///...`; `alembic upgrade head; alembic current` | **FAIL**: migration environment ignored runtime URL and still attempted hardcoded PostgreSQL. |
| `cmd /c openspec list` | **PASS**: showed active readiness changes; `live-readiness-blockers` complete, others partially complete. |

Warnings included SQLAlchemy `declarative_base` migration, Pydantic v2 class-config/`orm_mode`/`from_orm` deprecations, 4,000+ naive `datetime.utcnow()` deprecations, and SQLite test teardown warnings caused by the `users` ↔ `platform_integrations` FK cycle. No CI configuration was found. No live broker call was attempted.

## Readiness Scorecard

Scores are 0 absent, 1 foundational only, 2 partial, 3 workable for controlled paper with gaps, 4 beta-ready, 5 mature. Verification criteria are gates, not aspirations.

| Category | Score | Evidence | Current risk / blocker | Remediation and verification |
| --- | ---: | --- | --- | --- |
| Account onboarding | 3 | Registration, verification, recovery, profile, invite/legal/onboarding tests | Public registration abuse; email provider/runtime not verified | Distributed abuse gates and production email delivery; end-to-end invited-user test |
| Multi-user isolation | 2 | Many user-scoped queries and cross-user tests | No mandatory tenant repository/job/operator context | Two-tenant matrix across every route/job/export/admin read |
| Authentication/authorization | 2 | bcrypt, JWT, persisted sessions, reset revocation | localStorage token, no explicit logout, no MFA/risk auth, fragmented admin roles | Reviewed session/cookie design, CSRF/XSS tests, unified RBAC |
| Broker connectivity | 1 | Partial TopstepX and TradingView signal code; placeholders | No authorized production paper adapter; misleading credential collection | Capability manifest plus approved Tradovate/Alpaca conformance |
| Strategy configuration | 2 | Versioned RSI config and guardrails | No immutable activation snapshot/calendar binding | Draft/activate version tests and golden RSI compatibility |
| Paper trading | 3 | Durable immediate-fill paper ledger, demo, tests | Unrealistic fills/costs; no broker paper | Deterministic cost/liquidity models plus broker paper soak |
| Live execution safety | 1 | Live rejected before provider call | No safe live implementation or ceremony | Separate later proposal after every live gate and provider approval |
| Market-data correctness | 1 | Topstep history, stale strategy check | Unsupported TradingView data claim, polling, no sequence/calendar/license | Authorized data adapters, freshness/gap/clock tests |
| Order-state correctness | 2 | Idempotent paper lifecycle and models | Immediate fill only; no full provider events/unknown-state worker | State-machine and provider fault conformance |
| Risk management | 3 | Server risk settings, decisions, kill switch, daily state | Missing reservations and several limits/cancel/flatten semantics | Concurrency, exposure, loss, session, kill latency tests |
| Security/privacy | 1 | Encryption, config production checks, baseline redaction | Raw token logging, vulnerable deps, key lifecycle, placeholder privacy | Remove/rotate, KMS, seed-secret scans, zero unaccepted high findings |
| Auditability/explainability | 2 | Signal snapshots, risk/order/reconciliation records | No append-only end-to-end trace or operator read audit | Trace-completeness and tamper/redaction tests |
| Monitoring/alerting | 1 | Health/ops, JSON logs, local analytics | No external alerts, SLIs, delivery, provider/event lag dashboards | Injected-fault dashboard/alert verification |
| Reliability/recovery | 1 | Retry decisions and reconciliation locks | In-memory runs, no durable workers/outbox/game days | Restart/partition/DB/broker fault suite and recovery drills |
| Performance/scalability | 1 | Basic request limiter; 113-test suite | In-memory limiter, blocking requests in async adapters, no load evidence | Shared limits, async/bounded I/O, cohort load test |
| Accessibility/usability | 2 | Labels/status roles, frontend smoke/manual checklist | No automated browser/a11y suite; dense dashboard; missing account controls | Axe/keyboard/runtime viewport evidence and journey usability tests |
| Documentation/support | 2 | README, deployment/runbook/demo/accessibility docs, support routes | README overclaims integrations; smoke instructions fail; owner/SLA absent | Truthful docs and staffed support dry run |
| Legal/regulatory/disclosures | 1 | Versioned legal acceptance and placeholders | No reviewed terms/privacy/provider/data/compliance scope | Qualified review, jurisdiction/cohort rules, current consent tests |
| Deployment/rollback | 1 | Production config checks and deployment notes | Hardcoded Alembic URL, no CI/deploy manifest/rollback proof | Immutable pipeline, migration tests, backup/rollback game day |
| Testing/QA | 3 | 113 passing backend tests, frontend build/smoke | 4,455 warnings, slow suite, no browser/provider/load/security CI | Deterministic CI, warning budget, conformance/e2e/security/fault suites |

## Beta Blockers in Priority Order

1. Remove raw Topstep/session response logging and make all exception/log/analytics/support redaction complete; rotate any credentials that may have been logged.
2. Remediate the seven production npm advisories and establish pinned, scanned dependency builds for Python and Node.
3. Stop collecting credentials for roadmap/unsupported providers; correct TradingView data and multi-provider claims.
4. Establish mandatory tenant/operator authorization and purpose-bound audit; replace localStorage session design and add abuse controls.
5. Fix Alembic runtime configuration, fresh/upgrade migrations, the documented demo smoke, and protected CI.
6. Add account export/deletion, broker revocation, retention, and reviewed privacy/legal terms.
7. Replace in-memory bot sessions with durable commands, leases, outbox, checkpoints, and restart reconciliation.
8. Implement full order lifecycle, unknown-outcome idempotency, partial fills, balances/positions/P&L, and deterministic reconciliation.
9. Add transactional risk reservations, missing limits, trusted sessions/calendars, and measured kill/cancel/flatten behavior.
10. Obtain provider commercial/automation/data approval and implement one paper adapter at a time with conformance and soak evidence.
11. Establish production monitoring, support ownership, incident thresholds, backup/restore, rollback, and cohort gates.

## Proposed Safe Beta Scope

### Stage 0: Internal verification

- Fake/demo credentials only; local simulation; current RSI strategy.
- Required: full tests/build, no raw secret logging, known warnings/advisories tracked, daily owner review.
- Maximum: internal owner-approved accounts only.
- Exit: P0 build/security/migration/smoke/tenant fixes, traceable incidents, and all release documents drafted.
- Rollback: disable access, stop in-memory runs, preserve paper evidence.

### Stage 1: Invite-only simulation

- Local simulation only; no real broker credential required.
- Entry: no unaccepted high/critical production advisories; tenant/operator isolation; secure sessions; account export/delete; realistic disclaimers; durable runs; monitoring/support; successful backup/restore/rollback.
- Initial cap: owner-selected small cohort, proposed 10 users and one active run each until load/support data justifies expansion.
- Incident exit: any cross-user access, secret exposure, duplicate effective order, unrecoverable data loss, or kill-switch failure immediately pauses the cohort.
- Data: documented retention, self-service export/deletion, no broker secrets.

### Stage 2: Invite-only broker paper

- One provider at a time: Tradovate demo first for futures, optionally Alpaca paper as a separate cohort.
- Entry: written provider approval, capability conformance, OAuth/least privilege, full lifecycle/reconciliation, 30-day or owner-approved soak, zero unexplained drift/duplicates, staffed incident response.
- Proposed cap: 5 users/5 accounts for the first provider, then a reviewed increase.
- Rollback: disable adapter, block entries, reconcile all accounts, revoke grants if required, preserve audit.

### Stage 3: Limited live beta

- Not authorized by this proposal.
- Entry requires a separate OpenSpec change, approved provider/live account types, counsel/compliance sign-off, all 4/5+ category scores, zero critical blockers, live activation ceremony, independent safety review, recovery game days, and named on-call coverage.
- Any duplicate, unexplained drift, cross-tenant access, secret leak, missed risk limit, or kill failure is an automatic rollback trigger.

### Stage 4: Broader release

- Requires evidence from limited live, capacity/load testing, audited operations, provider expansion approvals, published support/pricing, and a fresh readiness review.

## Go/No-Go Criteria

Go requires all applicable stage requirements:

- Tests: unit, integration, two-tenant auth, adapter conformance, browser accessibility, migration fresh/upgrade, dependency/secret/static scans, restart/partition/DB/broker faults, backup/restore, rollback, and load at twice approved cohort.
- Security: zero applicable unaccepted critical/high findings, zero seeded secret leaks, approved key/session design.
- Correctness: zero duplicate effective orders in fault tests, deterministic reconciliation, cumulative fill/position/P&L agreement.
- Operations: monitored SLIs, named on-call/support, incident communication templates, provider disable and rollback drills.
- Product: persistent environment indicators, explicit limitations, current legal/privacy/risk acceptance, data export/deletion.
- Platforms: only evidence-dated, provider-approved environments with capability manifests and current commercial terms.

No-go is automatic for any critical security, authorization, execution, reconciliation, risk, data-loss, secret-management, paper/live-confusion, or unsupported-provider defect, regardless of average score or schedule.

## Known Limitations

- This review did not place live or broker-paper orders and did not validate real provider credentials.
- Local PostgreSQL was unavailable, and Alembic's hardcoded URL prevented a fresh migration run.
- The dependency audit reflects the installed lock state on 2026-07-26 and will change over time.
- Provider rules, regions, commercial approvals, and rate limits can change and require revalidation before implementation/release.
- Competitive documentation does not expose every security, audit, reliability, support, or pricing detail; unverified cells are not negative claims.
- Accessibility was checked by repository smoke/static expectations, not a complete assistive-technology user study.
- Legal, market-data licensing, adviser/broker-dealer, commodities/futures, privacy, tax, and jurisdictional obligations require qualified review.

## Owner Review Assumptions and Questions

- Assumption: the product is currently a hosted web service; if a signed local agent is acceptable, TopstepX feasibility changes but requires provider approval and a new threat model.
- Decide whether the initial broker-paper cohort is futures-only or includes Alpaca equities/crypto.
- Identify the contracting legal entity, intended jurisdictions, eligible users, and whether prop/evaluation accounts are in scope.
- Select KMS/vault, monitoring, email, backup, and hosting providers.
- Approve retention/deletion/legal-hold periods and incident-notification obligations.
- Name the security, operations, and support owners and publish response targets.
- Approve stage cohort caps, soak duration, readiness score thresholds, and risk-acceptance authority.
- Confirm whether the current `.env` Topstep credentials have ever been used with `app/auth.py`; if yes, rotate them because that helper prints tokens/responses.
