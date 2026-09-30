# Simulation Beta Readiness Report

## Hosted Combine risk/dry-run artifact checkpoint (2026-09-29)

The active hosted child now has versioned policy/consent/dry-run/proposal schema and deployment
templates in progress. Local policy validation, no-mutation adapter tests, and fresh SQLite/PostgreSQL
migrations are recorded in the child verification report. The hosted dry-run path fails closed without
authoritative Topstep read-only market, position/risk, and reconciliation evidence; no real provider
credentials are available. No Vercel/Railway deployment, real provider connection, dry-run acceptance,
or provider order evidence exists. Do not treat artifact creation as hosted beta approval.

Assessment baseline: 2026-07-26 P0 remediation plus repository state at change creation.

## Implementation checkpoint

External beta remains **NO-GO**; internal testing remains **GO**. This checkpoint added envelope-encryption and production fail-closed primitives, tenant repository/job-envelope primitives, additive durable run/lease/command/checkpoint/outbox records, correlated operator outcomes, deletion cancellation/tombstones, an application restore drill, and release-rule documentation.

Full backend verification passed **130 tests with 5,307 warnings in 409.74 seconds**. The prior baseline was approximately 5,202 warnings; the increase and absence of an enforced warning budget independently block beta. Hardware-backed production key management/offline recovery/physical TPM evidence, universal tenant migration, durable scheduler/recovery integration, complete failure injection, managed backup evidence, clean installs/audits, host CI evidence, and owner operations approvals also remain open.

## Durable control-plane checkpoint — 2026-07-29

Start, pause, resume, stop, status, and kill are now tenant-scoped durable operations. Risk kill-switch activation durably kills matching runs. The former unauthenticated SSE execution loop is authenticated and status-only, so an SSE request or process dictionary no longer owns execution. A periodic database recovery/outbox worker validates signed tenant jobs.

Direct PostgreSQL 17 evidence passed three concurrency tests: different-key same-scope starts produce one active run; concurrent same-key starts return one run/command; concurrent duplicate pause returns one command. Focused SQLite evidence passed 20 tests.

This slice is not complete: crash-boundary and database-interruption injection, all interrupted-state combinations, complete risk/ledger/reconciliation recovery, stale-market recovery, and full restart proof remain open in `failure-injection-matrix.md`. Invite-only simulation beta therefore remains **NO-GO**, independently of the other physical-TPM/recovery, universal-tenant, warning, reproducibility, operations, and host-CI blockers.

Final slice verification: the first full run produced **144 passed, 3 skipped, 1 failed, 6,091 warnings in 474.87s** because SQLite requires named foreign keys and Alembic batch alteration. After correction, the failed migration test passed and the final full run produced **145 passed, 3 skipped, 6,085 warnings in 469.50s**. The three skips are the intentionally opt-in PostgreSQL concurrency module; it was separately run against PostgreSQL 17 with `DURABLE_POSTGRES_TEST_URL` and passed **3/3**.

The warning count increased from **5,307 to 6,085 (+778)**, largely because the new database-heavy tests exercise existing naive-UTC and SQLAlchemy/Pydantic deprecations. No budget is enforced, so warning control remains an independent veto.

## Durable evaluation and recovery checkpoint — 2026-07-29

Automated simulation evaluation is restored without restoring the removed SSE
executor. Authenticated HTTP routes persist controls and deterministic
simulation inputs only. The periodic worker is the sole evaluator and uses the
persisted tenant/run/lease/fence as authority.

The worker now classifies stable market identities and freshness, deterministically
evaluates `rsi-threshold-v1`, applies risk and reconciliation gates, persists a
signal, a distinct simulated submission and modeled fill, position/account/P&L,
fee-bearing ledger effect, daily and run risk counters, outbox events, and an
integrity-hashed checkpoint in one transaction. Recovery validates the
configuration, strategy, checkpoint digest, market sequence, evaluations,
orders, fills, positions, accounts, ledger, fees, and risk state. Disagreement
fails closed.

Direct PostgreSQL 17 tests cover duplicate workers, `SKIP LOCKED`, database
termination during heartbeat/command/market/outbox work, and kill races at
eight transaction boundaries. The real subprocess drill passed: a worker exited
with code 91 before commit, the replacement acquired a higher fence and
recovered, two inputs produced exactly two evaluations/orders/fills/ledger
effects and risk increments, and a killed run remained Killed with zero effects
after another process restart. Reports are retained in `evidence/`.

This closes the durable execution application tasks only. Invite-only
simulation beta remains **NO-GO** because hardware-backed production key management, offline recovery, physical TPM drills/evidence,
universal tenant migration beyond these paths, warning-budget
enforcement, clean-lock installation evidence, operator/account lifecycle
completion, application operations, owner approvals, and protected-host CI
remain independent critical vetoes.

Final verification for this slice:

- full backend: **175 passed, 17 skipped, 6,896 warnings in 530.80s**;
- PostgreSQL-only durable concurrency/recovery: **17 passed, 574 warnings in 8.52s**;
- real subprocess restart drill: **PASS**;
- fresh PostgreSQL 17 migration: one linear head at `fb2e3f4a5b6c`;
- frontend: **2 tests passed**, production build **87 modules**, production audit **0 vulnerabilities**;
- demo smoke: **PASS**, with live execution still rejected;
- strict OpenSpec validation: **PASS**.

The previous full-suite warning count was 6,085. The current count is 6,896
(+811), with 30 new database-heavy tests. New durable code uses aware UTC; the
remaining warnings are dominated by existing model defaults, observability,
authentication, and dependency deprecations. Because no enforced budget exists,
this increase is not accepted as a resolved quality gate.

## Universal tenant-enforcement checkpoint — 2026-09-22

Tasks 2.1-2.4 are implemented. Authentication now binds an immutable trusted
tenant/actor/session context to the request database session after JWT, active
session, CSRF, and active-user validation. Request-facing integrations,
simulation status/control, scheduler aliases, risk, reconciliation, launch
gates, account export/deletion, support, analytics, subscription administration,
and authenticated session management use non-escaping tenant repositories.
Legacy service queries inherit automatic tenant criteria and cross-tenant flush
rejection from that bound session.

Signed job envelopes now bind tenant, actor, job identity/type, purpose, issuer,
environment, issue/expiry, correlation/causation, payload hash, nonce, and
version. Cross-tenant worker discovery is restricted to four named maintenance
purposes, and every effect re-establishes a verified tenant before the existing
run/fence checks. Status polling and the compatibility SSE endpoint perform
tenant repository lookups; no WebSocket route exists.

Operator access creates a five-minute purpose/case/action/target context and
retains actor identity. Target data uses the ordinary tenant repository. Global
operator metadata is limited to invite, plan, and legal-document models. The
pre-auth identity/token bootstrap and the `APP_ENV=test` webhook fixture are the
only direct-query request allowlist entries; a syntax-aware CI check rejects new
ones.

Migration `fc3f4a5b6c7d` adds non-null tenant identity and tenant-inclusive
foreign keys to outbox delivery and provider revocation records, aborting on an
underivable legacy row. Fresh SQLite and PostgreSQL 17 migrations reached one
linear head. PostgreSQL directly rejected mismatched delivery and revocation
relationships and verified tenant-bounded bulk update/delete behavior (**3/3
tests passed, 18 warnings**). The focused universal matrix passed **40 tests**
after expansion, with additional API/lifecycle suites covering all run controls,
market queue, status/SSE, export, and deletion.

This checkpoint closes the universal tenant application tasks only. It does not
claim PostgreSQL RLS, statistically constant-time responses, managed backup
purge, host branch protection, or completion of the overall simulation-beta
gate. Invite-only simulation beta remains **NO-GO** because managed production
physical TPM/recovery drill, warning-budget enforcement, clean locked-install evidence,
complete operator outcome and deletion/backup tasks, operational approval, and
protected-host CI remain independent vetoes.

### Final verification evidence — 2026-09-22

The final serial backend run completed with **218 passed, 20 skipped, and 7,043
warnings in 737.38 seconds**. The focused tenant/context suite passed 43 tests
with 40 warnings; the PostgreSQL constraint suite passed 3 tests with 18
warnings. Frontend tests passed 2 tests, the production build succeeded, and
`npm audit --omit=dev` reported zero vulnerabilities. `pip check`, compileall,
fresh SQLite/PostgreSQL migrations, demo smoke, strict OpenSpec validation, and
`git diff --check` passed. `pip_audit` was unavailable because the module is not
installed; the default-host PostgreSQL current command was unavailable without
a running server, while the disposable PostgreSQL migration reached the single
head `fc3f4a5b6c7d`.

This evidence closes tasks 2.1–2.4 only. The warning-budget gate, physical TPM/recovery,
clean locked-install, operator outcomes, deletion/managed-backup, operational
approval, and protected-host CI requirements remain open.

### Owner key-management decision checkpoint - 2026-09-23

The owner prohibited AWS, all other cloud KMS products, and hosted secrets services. The prior child `implement-aws-kms-envelope-encryption-and-roles-anywhere` is superseded before production integration; provider-neutral envelope work was retained, cloud-specific code/dependencies/configuration/templates/tests/guidance were removed, and its four incomplete tasks remain incomplete.

The authoritative replacement is `replace-aws-kms-with-tpm-backed-local-key-management`: physical TPM 2.0 on a self-hosted Raspberry Pi, persistent non-exportable RSA-OAEP-SHA256 wrapping keys, schema-2 per-record AES-GCM envelopes, fingerprint pinning, data-key-only rotation, explicit Fernet cutover, and separately protected offline recovery wrapping. Deterministic software tests do **not** close physical provisioning, non-exportability, reboot/restart/upgrade, lockout/failure, PostgreSQL concurrency, restored-backup replacement-Pi recovery, production Fernet migration, key retirement, custody, or operational approval.

## Initial Recommendation

| Stage | Initial decision | Reason |
| --- | --- | --- |
| Internal testing | GO | Existing paper/demo, risk, kill, reconciliation, security, migration, and test evidence passes. |
| Invite-only simulation beta | NO-GO | Managed secrets, universal tenant enforcement, durable run recovery, deletion/restore drill, warning budget, clean-install evidence, operations, and protected CI evidence remain incomplete. |
| Broker paper-account beta | NO-GO | No approved adapter or sandbox conformance is in scope. |
| Live-money beta | NO-GO | Live remains prohibited and no live release requirements are implemented. |

## Verified Baseline

- Cookie/CSRF sessions, revocation, rotation, and logout.
- Central log/exception redaction and removed Topstep token/response printing.
- Runtime Alembic URL and a linear PostgreSQL-verified migration chain.
- Purpose/case/target operator authorization decisions.
- Provider truthfulness: TopstepX unavailable hosted; TradingView signals only.
- Tenant-scoped export/deletion and shared database rate limits.
- 120 backend tests, two frontend tests, clean production npm audit, and strict prior change validation.

## Critical Open Gates

1. Production managed-key provider selection and drill.
2. Universal tenant enforcement and structural check.
3. Durable fenced runs, commands, outbox, checkpoint, and failure-injection evidence.
4. Complete operator terminal outcomes.
5. Deletion tombstones and backup/restore drill.
6. Enforced warning budget from the approximately 5,202-warning baseline.
7. Clean locked installation evidence.
8. Application-owned cohort/incident/health controls and owner policy approvals.
9. Confirmed protected-branch checks and retained host evidence.

## Decision Rule

Simulation beta is GO only if every P0 application task and owner-controlled gate is complete with direct traceability. A passing average or test suite cannot override a critical open gate.

## 2026-09-24 Hosted Trading Combine target decision

The immediate target is a one-user Topstep Trading Combine beta: Vercel frontend only; separate Railway API and durable worker; Railway PostgreSQL and Redis; and TopstepX simulated provider access. Physical TPM work remains incomplete and is deferred as a blocker only for this hosted stage. The hosted exception is the explicit `railway-secret-envelope-v1` provider, whose Railway-administrator/runtime exposure is an accepted narrow risk and is not TPM-equivalent.

| Release stage | Current disposition | Controlling evidence |
|---|---|---|
| Internal software testing | GO if regressions remain absent | Local software verification |
| Invite-only internal simulation | GO if existing internal gates remain passing | Durable simulator, tenant, risk, recovery, and kill evidence |
| One-user Topstep Trading Combine beta | NO-GO pending child completion | Hosted provider, deployment, exact-account approval, consent, dry run, risk, restart, backup, deletion, and provider acceptance |
| Express Funded Account beta | NO-GO | Explicitly out of scope and prohibited |
| Live Funded/live-brokerage beta | NO-GO | Server-side live rejection remains mandatory |

A Trading Combine is simulated but carries real evaluation, rule-compliance, and subscription-value consequences. Explicit tester consent is mandatory. No Vercel, Railway, Topstep, or provider-order evidence exists merely because local tests pass.

## 2026-09-25 durable Topstep onboarding checkpoint

The hosted child added a linear schema through `fe5b6c7d8e9f` for tenant-bound encrypted credential generations and sessions, discovery evidence, versioned Trading Combine attestation, purpose-bound operator approval, and deletion tombstones. Local deterministic fixtures cover connect, encryption, replacement rollback, exact-account attestation/approval, centralized eligibility, idempotent deletion, run kill, outbox suppression, and cross-tenant access. A disposable PostgreSQL 17 migration reached the single head, rejected a cross-tenant credential relationship, and allowed exactly one of two concurrent different-account approvals to commit.

Legacy metadata/first-account authorization and all Topstep order-submit paths now fail closed. At this 2026-09-25 checkpoint, encrypted session refresh after expiry was open; the 2026-09-29 continuation below records local renewal implementation and tests. The PostgreSQL race matrix, restored-backup revocation, dry run, risk policy, Railway/Vercel deployment, real credentials, provider evidence, and external key revocation remain open. The Trading Combine beta remains **NO-GO**. Internal software testing remains **GO** only if final regressions pass; internal simulation retains its existing disposition; Express Funded and Live Funded/live brokerage remain **NO-GO**.

## 2026-09-25 durable Topstep session and restore-safety checkpoint

The hosted child now uses database-authoritative provider sessions with generation binding,
renewal-not-before policy, single-owner leases, monotonic fencing, `/api/Auth/validate` token
rotation, controlled current-generation reauthentication, and typed redacted failures. Replacement,
revocation, deletion, expiry, and a security-epoch change override renewal. Credential-dependent
runs, commands, and outbox work carry generation/epoch identities and consumers fail closed.

`HOSTED_SECURITY_EPOCH` is an external non-secret monotonic restore contract. A higher environment
epoch disables eligibility and recovery processing until an authorized revoke-by-default ceremony
erases restored credentials/sessions, revokes approvals/attestations, kills runs, cancels commands,
suppresses outbox work, and advances the database epoch. Epoch rollback is rejected. This is
software evidence only: no Railway backup-platform restore has been performed.

A fresh SQLite and PostgreSQL 17 database currently migrate to the sole head `ff6c7d8e9f0a`. On
2026-09-29, 66 PostgreSQL durable execution/evaluation, key rotation, tenant, onboarding, and session
race/invariant tests passed, plus a PostgreSQL restore-reconciliation integration test passed. The
suite contains two actual concurrent renewal lease/takeover tests and 40 parameterized fail-closed
lifecycle/restore invariant scenarios; the latter are not 40 independent concurrent race
reproductions. A PostgreSQL deletion fixture also found accepted commands were not suppressed; the
implementation now cancels pending, accepted, claimed, and processing work, and the corrected
deletion test passes. The full requested race matrix and real backup-platform restore remain open.
Deterministic local failure injection and focused SQLite suites are recorded in the hosted child
verification report. The full backend run is 297 passed, 67 skipped, and 7,453 warnings. The Trading
Combine stage remains **NO-GO** because dry
run/risk execution, external deployment, real-provider acceptance, real backup restore, tester
offboarding, operational approvals, and explicit order authorization remain open.

## 2026-09-29 full regression checkpoint

The current backend suite completed with 297 passed, 67 skipped, and 7,453 warnings in 722.98 seconds.
The 67 skips include PostgreSQL/service-gated tests because the Docker Desktop engine was unavailable;
the newest schema and PostgreSQL race/restore tests therefore remain open. The prior full run had
273 passed, 23 skipped, and 7,199 warnings: this run adds 24 passing tests, 44 environment/service
skips, and 254 warnings. `pip check`, `compileall`, focused frontend tests, fresh SQLite migration,
and strict OpenSpec validation passed. `pip_audit` was not installed; current frontend clean install,
build, audit, demo, PostgreSQL, Vercel/Railway, and real-provider checks remain outstanding. The
warning-budget gate remains unresolved. Internal software testing is GO only in the existing
conditional sense; invite-only Trading Combine remains **NO-GO**; Express Funded and Live Funded/live
brokerage remain **NO-GO**.

## Hosted risk/dry-run regression checkpoint — 2026-09-29

Post-fix backend verification now passes with 303 passed, 68 skipped, and 7,420 warnings
(1,399.33 s). The prior checkpoint was 297 passed, 67 skipped, and 7,453 warnings. The 33-warning
reduction is recorded, but does not satisfy warning-governance approval. PostgreSQL availability
was restored in a disposable local container: the current schema reached the one linear head
fg7d8e9f0a1b from empty PostgreSQL and SQLite databases; targeted PostgreSQL policy uniqueness and
tenant-FK tests passed. Frontend clean install, three frontend tests, production build, production
dependency audit (zero vulnerabilities), secret scan, demo smoke, configured imports, compileall,
pip check, and strict validation of parent/TPM/hosted changes passed. Python pip_audit remains
unavailable. The unconfigured deployment preflight correctly failed closed (40 missing/invalid
checks); no external deployment, Topstep call/credential/order, or backup-platform restore occurred.

Risk-policy and consent route-level coverage, read-only Topstep account/market/reconciliation
evidence, deployed Vercel/Railway checks, exact preview-origin verification, owner risk values,
backup restore, complete individually orchestrated PostgreSQL races (tasks 7.4/11.4), and warning
approval remain open. Therefore internal software testing remains conditionally GO; internal
simulation remains conditional on existing gates; deployed hosted preview and one-user Combine
provider-order beta remain NO-GO pending their evidence. Express Funded and Live Funded/live
brokerage remain NO-GO.
