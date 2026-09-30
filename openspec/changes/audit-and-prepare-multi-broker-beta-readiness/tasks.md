## 1. Beta Blockers: Build and Deployment Integrity

- [ ] 1.1 Pin Python production dependencies with hashes or a reviewed lockfile; completion is `pip install` from a clean environment plus `python -m pip check` and the full test suite passing.
- [x] 1.2 Upgrade vulnerable frontend production dependencies; completion is `npm audit --omit=dev` reporting no unaccepted high/critical findings and `npm run build` passing.
- [x] 1.3 Make Alembic consume the runtime `DATABASE_URL` rather than the hardcoded URL in `alembic.ini`; completion is fresh and upgrade migration tests on supported PostgreSQL plus `alembic current` matching `alembic heads`.
- [x] 1.4 Repair `scripts/demo_smoke.py` and its database setup so the documented `python scripts/demo_smoke.py` command passes from repository root without manual `PYTHONPATH` or pre-created tables.
- [ ] 1.5 Add CI for backend tests, frontend build, dependency/secret/static scans, migration fresh/upgrade tests, and strict OpenSpec validation; completion is one protected-branch run with all required checks green and retained artifacts.
- [ ] 1.6 Eliminate or explicitly budget the 4,455 current warnings; completion is a documented warning baseline with new warnings failing CI and timezone-aware/Pydantic/SQLAlchemy/FK-cycle migrations scheduled or fixed.

## 2. Beta Blockers: Identity, Isolation, and Abuse Controls

- [ ] 2.1 Introduce mandatory tenant context in repositories, routes, exports, jobs, and analytics; completion is automated two-tenant isolation coverage for every sensitive resource and worker command.
- [ ] 2.2 Replace browser `localStorage` bearer-token persistence with a reviewed session design using secure, HttpOnly, SameSite cookies or an equivalent threat-modeled mechanism; completion is XSS/session fixation/CSRF tests and session revocation regression coverage.
- [ ] 2.3 Add explicit current-session logout, login throttling, registration/invite abuse controls, verification/reset throttles, and security-event alerts; completion is automated brute-force, enumeration, replay, and revoked-session tests.
- [ ] 2.4 Add role-based, purpose-bound operator access with case IDs and audit events; completion is non-admin denial tests and an audit trace for every operator read or mutation.
- [ ] 2.5 Implement account export and deletion with reauthentication, broker revocation, retention/legal-hold policy, deletion receipt, and backup behavior; completion is end-to-end export/delete/restore-isolation tests.

## 3. Beta Blockers: Credentials and Provider Truthfulness

- [ ] 3.1 Select managed KMS/vault infrastructure and implement versioned envelope encryption, dual-read key rotation, non-redisplayable secrets, and cryptographic erasure; completion is rotation/recovery tests and a restore drill.
- [ ] 3.2 Extend redaction tests across HTTP errors, provider payloads, structured logs, exception traces, analytics, Sentry, support records, exports, and backups; completion is seeded-secret scanning with zero plaintext matches.
- [x] 3.3 Replace provider marketing lists with evidence-dated supported, beta, planned, unsuitable, and unsupported states; completion is UI/API tests proving roadmap providers collect no credentials and expose exact blockers.
- [ ] 3.4 Obtain and record commercial/API/market-data approval for each beta provider; completion is owner-approved evidence with scope, regions, permitted hosting model, automation policy, expiry/review date, and incident contact.

## 4. Beta Blockers: Durable Execution and Risk

- [ ] 4.1 Replace process-global bot sessions and rate buckets with durable bot runs, commands, leases, checkpoints, and shared rate limiting; completion is multi-worker restart/duplicate-lease tests with no lost or duplicate run.
- [ ] 4.2 Add a transactional outbox and idempotent worker consumer; completion is crash-before/after-commit fault tests proving exactly one effective command.
- [ ] 4.3 Implement immutable environment-scoped order intents and the specified lifecycle state machine; completion is transition-table tests for acceptance, rejection, partial fill, cancel, replace, expiry, and unknown submission.
- [ ] 4.4 Enforce provider client-order IDs where available and unknown-outcome reconciliation before retry; completion is timeout/restart/network-partition tests proving no duplicate order.
- [ ] 4.5 Derive positions, balances, realized P&L, and unrealized P&L from fills and broker snapshots; completion is partial-fill, bust/correction if supported, cancel remainder, and restart projection tests.
- [ ] 4.6 Make reconciliation run at startup, reconnect, event gaps, unknown outcomes, and intervals with deterministic conflict policy; completion is order/fill/position/balance drift tests that lock rather than silently overwrite ambiguity.
- [ ] 4.7 Add transactional risk reservations and limits for daily loss, notional/exposure, trade count, consecutive loss, sessions, stale data, connectivity, and pending orders; completion is concurrent-order tests that cannot exceed limits.
- [ ] 4.8 Define and test kill-switch block, cancel, and flatten semantics per provider; completion is measured server-side activation latency and outage/restart tests with new entries blocked.

## 5. Beta-Critical Improvements: Configuration, Simulation, and Explainability

- [ ] 5.1 Add draft and immutable activated configuration versions binding environment, account, instrument, calendar, data source, `rsi-threshold-v1`, risk, schedule, and notifications; completion is edit-without-mutating-running-version tests.
- [ ] 5.2 Add provider instrument metadata, exchange calendars, timezone/holiday/DST validation, and clock-drift gates; completion is closed-session, rollover, DST, stale-calendar, and clock-offset tests.
- [ ] 5.3 Preserve `rsi-threshold-v1` defaults while adding a strict parameter schema and rationale records; completion is golden signal tests plus malicious/oversized/unknown parameter rejection.
- [ ] 5.4 Upgrade local simulation to configurable spread, slippage, fees, margin, liquidity, session, and contract-expiry models; completion is deterministic fixtures and reports itemizing every modeled cost/assumption.
- [ ] 5.5 Make backtests reproducible and bias-aware with data/version fingerprints, cost models, out-of-sample splits, and optional walk-forward evaluation; completion is deterministic reruns and explicit look-ahead/survivorship validation tests.
- [ ] 5.6 Implement append-only audit events and a user trace from market input through fill/P&L; completion is one end-to-end trace test and tamper/redaction verification.
- [ ] 5.7 Add accessible start, pause, resume, stop, kill, disconnect, export, and delete controls with persistent environment state; completion is automated accessibility checks plus 390/768/1440-pixel runtime evidence.

## 6. Beta-Critical Improvements: Operations and Release Gates

- [ ] 6.1 Instrument market-data age, clock offset, worker leases, provider health/rate limits, token refresh, order age, unknown outcomes, reconciliation drift, risk locks, kill latency, and notifications; completion is dashboard/alert tests using injected failures.
- [ ] 6.2 Add user-visible healthy, degraded, paused, reconciling, and incident-blocked states; completion is runtime fault tests proving unsafe degraded states fail closed.
- [ ] 6.3 Define notification channels, deduplication, delivery tracking, and severity routing; completion is authentication, broker, order, risk, reconciliation, and incident notification tests.
- [ ] 6.4 Complete reviewed terms, privacy, paper-risk, data-retention, automation, market-data, and support disclosures; completion is owner/counsel approval with current version acceptance gates.
- [ ] 6.5 Publish support ownership, hours, response targets, incident severity, escalation, and known limitations; completion is a staffed dry run from user report through closure.
- [ ] 6.6 Automate stage-specific release gates and cohort caps; completion is tests proving any critical blocker overrides the readiness average and prevents admission.
- [ ] 6.7 Perform backup, restore, incident-response, provider-disable, rollback, and reconciliation game days; completion is timestamped evidence meeting recovery objectives with no cross-tenant or secret exposure.

## 7. First Broker-Paper Integrations

- [ ] 7.1 Implement the capability-manifest and canonical adapter conformance harness; completion is shared contract tests proving typed unsupported behavior for every operation.
- [ ] 7.2 Implement a Tradovate demo adapter using an approved OAuth/delegated flow, demo endpoints, user-data streaming, market data, lifecycle events, and rate handling; completion is provider-sandbox conformance plus forced disconnect/partial-fill/rejection tests.
- [ ] 7.3 Implement an Alpaca paper adapter with separate paper credentials/domain, account/instrument discovery, market-data and trade-update streams, client order IDs, and rate handling; completion is paper-account conformance and environment-confusion tests.
- [ ] 7.4 Run an internal soak for each adapter; completion is at least the owner-approved duration with zero duplicate orders, zero unexplained drift, reconciled restarts, and all injected incidents detected.
- [ ] 7.5 Admit a capped broker-paper cohort only after stages 1-6 pass; completion is signed go/no-go evidence, user consent, support coverage, and exit/rollback criteria.

## 8. Post-Beta Improvements

- [ ] 8.1 Add richer user-defined notification preferences and mobile/PWA ergonomics; completion is delivery and accessibility tests across supported devices.
- [ ] 8.2 Add portfolio-level analytics, downloadable tax-neutral execution reports, and comparison of modeled versus broker paper fills; completion is reconciliation against provider statements.
- [ ] 8.3 Add organization accounts and delegated team roles if demanded; completion is tenant/role isolation and audit coverage.
- [ ] 8.4 Evaluate a dedicated message broker and read models against measured PostgreSQL queue limits; completion is a documented benchmark and migration decision.

## 9. Future Platform Integrations

- [ ] 9.1 Pursue IBKR third-party compliance approval, OAuth onboarding, funded IBKR Pro prerequisites, paper market-data entitlements, and regional restrictions before implementation; completion is written approval and an accepted adapter plan.
- [ ] 9.2 Evaluate NinjaTrader REST Trade API and WebSocket Market Data access, demo environments, commercial terms, and overlap with Tradovate; completion is a dated technical/contractual decision.
- [ ] 9.3 Evaluate OANDA practice for a region-limited forex cohort; completion is authorization, instrument, streaming, rate-limit, and regional conformance evidence.
- [ ] 9.4 Re-evaluate Coinbase only when a realistic forward paper environment or approved controlled live test model exists; completion is evidence beyond the current static Advanced Trade sandbox.
- [ ] 9.5 Re-evaluate TopstepX only for an architecture compliant with personal-device origin rules and account-type automation restrictions; completion is written provider approval for the intended deployment and a non-live sandbox/test plan.
- [ ] 9.6 Record platforms without an authorized official API as unsupported; completion is quarterly evidence review with no browser automation or credential-scraping code.
