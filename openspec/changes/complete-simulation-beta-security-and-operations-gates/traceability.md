# Requirement Traceability

| Hosted risk/dry-run control | Implementation/evidence | Status |
| --- | --- | --- |
| Server-owned versioned risk policy | `HostedCombineRiskPolicy`, operator policy route, strict validator, partial unique active-policy index | Software slice implemented; owner risk values not selected |
| Versioned Combine consent | `HostedCombineConsent`, exact text/version and generation/account/approval/policy binding | Software slice implemented; hosted tester consent evidence open |
| Durable isolated dry run | `HostedCombineDryRun` and `HostedCombineProposal`, worker lease/fence, idempotency, current-state recheck | Partial; Topstep read-only provider/risk evidence absent, so worker degrades |
| Mutation-disabled provider boundary | Topstep capability map omits broker trading; place/cancel/modify/close reject; startup guards | Local automated evidence only |
| Deployment readiness | `frontend/vercel.json`, `railway.toml`, `Dockerfile`, worker entrypoint, preflight, runbook | Templates only; deployed evidence and preflight with actual secrets/policy open |
| Full post-fix regressions | Child `verification.md` | Open until final backend/frontend/dependency/PostgreSQL results appended |

Implementation checkpoint: universal tenant enforcement and durable simulation
evaluation/recovery are verified for beta-reachable paths; physical TPM and offline recovery evidence,
operator outcomes, deletion/managed-backup completion, warning control, clean
installation, operations, and host CI remain open. Broker/live separation remains
verified. See the readiness report for current command evidence and vetoes.

## Universal tenant-enforcement slice — 2026-09-22

| Requirement | Implementation evidence | Automated/runtime evidence | Status / remaining gap |
| --- | --- | --- | --- |
| complete inventory | `tenant-enforcement-inventory.md` maps models, routes, services, workers, streams, lifecycle, offline and test paths | request-module source scan | Verified for mounted application and worker paths |
| immutable request context | `authorization.TenantContext`; auth binds after JWT/session/CSRF/user validation | session/API suites and missing/conflict cases | Verified |
| complete job context | `VerifiedTenantJob` v2 signs tenant/actor/type/purpose/issuer/environment/payload/expiry | tenant, actor, type, purpose, issuer, environment, payload, signature and expiry cases | Verified |
| mandatory repository | `TenantRepository` value-returning CRUD/list/count/lock/bulk/audit ports plus session ORM/flush guard | 40-case focused matrix and API suites | Verified for beta request paths; internal service ORM remains guarded compatibility code |
| durable tenant propagation | named discovery scopes; each effect binds a signed job before existing fence checks | durable command/evaluation/recovery/outbox regressions | Verified |
| streams/status | simulation polling and status-only SSE use repository lookups | foreign status/SSE return 404 with zero effects | Verified; no WebSocket route exists |
| operator scope | expiring `OperatorContext`; target repository; narrow global metadata `OperatorRepository` | role/purpose/case/target/expiry negatives and existing audit API tests | Verified authorization boundary; complete post-action outcome task 4 remains open |
| export/deletion isolation | repository-driven export, deletion, session revocation and tombstone path | cross export plus foreign execute/cancel DB assertions | Verified; managed backup purge remains open |
| indirect tenant relationships | migration `fc3f4a5b6c7d`; direct tenant columns and composite FKs | fresh SQLite/PG migrations; 3 PostgreSQL constraint/bulk tests | Verified |
| architectural enforcement | `tenant_architecture.py` AST scan; documented two-function category allowlist | real tree + prohibited/allowed fixture cases; CI command | Verified locally; protected-host result remains open |
| negative matrix | `cross-tenant-negative-matrix.md` | repository, API, lifecycle, durable and PostgreSQL suites; final backend regression | 48 rows covered; focused 43 passed, final backend 218 passed |

Tasks 2.1-2.4 close on this evidence. Overall simulation beta stays NO-GO for
independent TPM/recovery, warning, clean-install, operations, operator-outcome,
deletion/managed-backup, and protected-host gates.

## Durable control-plane slice — 2026-07-29

| Requirement | Implementation | Automated evidence | Status / gap |
| --- | --- | --- | --- |
| authoritative durable controls | scheduler start/stop aliases and `simulation_routes.py` use `submit_start`/`submit_command` | API control tests | Verified for control paths |
| no process-local execution authority | legacy SSE is authenticated status-only; dictionaries are compatibility markers only | architectural source test | Verified; compatibility symbols remain for older internal tests |
| concurrent active scope/start key | tenant row lock and unique active scope | 3 direct PostgreSQL concurrency tests | Verified |
| state machine/fencing | `durable_simulation.py` and migrations through `fa1d2e3f4a5b` | state, lease, stale effect tests | Verified primitives |
| kill precedence | risk kill atomically submits durable run kills; fence invalidated | API and direct kill tests | Verified for covered states; complete matrix partial |
| checkpoint/recovery | compatible checkpoint validation and periodic recovery worker | recovery/mismatch tests | Partial: risk/reconciliation/stale-market recovery incomplete |
| outbox | transactional event insertion, expiring claims, redelivery, durable delivery/failure rows | outbox redelivery/poison tests | Verified primitives |
| failure injection | `failure-injection-matrix.md` | SQLite transaction injection, PostgreSQL termination/races, and subprocess drill | Verified for tasks 3.6–3.7 |

## Durable evaluation/recovery slice — 2026-07-29

| Requirement | Implementation evidence | Automated/runtime evidence | Status / remaining gap |
| --- | --- | --- | --- |
| stable market identity/freshness | `SimulationMarketInput`, source/content digests and worker classifications in `simulation_evaluation.py` | stale, duplicate, conflicting/integrity and post-recovery tests | Verified for deterministic simulation feed |
| deterministic `rsi-threshold-v1` | pure `evaluate_rsi_threshold` bound to version/config/lookback | identical replay test and worker workflow tests | Verified |
| fenced atomic economic workflow | one run-locked transaction for evaluation, risk, order, fill, position, account, ledger, counter, outbox, checkpoint | eight crash-boundary rollback cases; PG duplicate workers | Verified |
| complete checkpoint | canonical checkpoint payload/hash and run hash pointer | corruption, sequence, configuration, strategy, position/risk/ledger drift tests | Verified |
| recovery reconciliation | `reconcile_checkpoint` plus `recover_owned_run` | Starting/Running/Pausing/Stopping/Recovering tests | Verified |
| kill transaction ordering | run-row serialization and fence invalidation | PG eight-boundary kill races; kill-first and stale returned-owner tests | Verified |
| database interruption | transaction rollback/reclaim behavior | PG backend termination for heartbeat, command, market, outbox | Verified |
| real process restart | `scripts/durable_simulation_restart_drill.py` | retained JSON/Markdown PASS evidence | Verified |
| tenant isolation | tenant-required queue/evaluation and verified worker envelopes | cross-tenant input/workflow and job-envelope negatives | Verified for migrated durable paths; universal repository task remains open |
| no request-owned execution | scheduler/routes only persist commands/input; SSE status-only | architectural source enforcement | Verified for beta-reachable simulation controls/evaluation |
| paper/live separation | automated records are local simulation; manual paper path unchanged; backend live rejection unchanged | 175-test backend suite, manual paper/provider/demo suites | Verified for this slice |

| Capability | Baseline evidence | Planned implementation/tests | Initial status |
| --- | --- | --- | --- |
| Hardware-backed secret protection | Legacy Fernet inventory not yet executed; production physical key absent | Schema-2 envelope, TPM provider boundary, context/tamper/rewrap/recovery mock tests, owner TPM decision | Partial; blocked on physical Pi/TPM, PostgreSQL, migration, restore/recovery, retirement and approval evidence |
| Tenant isolation | Bound immutable context, repositories, ORM/flush guard, signed jobs and PG constraints | Architectural, 48-row negative matrix and PostgreSQL relationship tests | Verified for beta-reachable paths |
| Durable bot execution | Persisted fenced controls and deterministic evaluation/recovery | Failure matrix, PostgreSQL concurrency and real process drill | Verified for application scope |
| Operator auditing | Authorization decisions in `SecurityAuditEvent` | Correlated start/terminal outcome service and operator coverage | Partial |
| Deletion/backup | Export, anonymization, session revocation, revocation attempts | Cancellation/tombstone/backup restore drill and owner game day | Partial |
| Dependency reproducibility | Exact locks; existing environment tests | Empty venv installs, clean npm ci, audits/import/migrate/test/demo | Partial |
| Warning control | 5,202 warnings in last full run | Inventory, remediation, committed budget, CI check | Blocked |
| Simulation onboarding | Invite/legal/onboarding and simulation labels | Cohort/eligibility/acknowledgement/config journey tests | Partial |
| Simulation recovery | Paper idempotency/risk/kill/reconciliation | Durable controls and restart/duplicate/stale-worker tests | Blocked |
| Beta operations | Invite/support/health endpoints | Cap/suspension/maintenance/degraded/feedback controls plus owner policy | Partial |
| Release governance | CI definition and strict OpenSpec | Evidence manifest, expanded checks, host branch evidence | Partial |
| Hosted Combine key protection | Railway service-variable boundary and schema-2 envelopes | `RailwaySecretEnvelopeProvider`, configuration guards, rotation/context/tamper tests | Software implementation; external Railway evidence open; accepted narrow risk |
| Topstep Combine deployment | Vercel frontend; separate Railway API/worker/PostgreSQL/Redis | `deploy-invite-only-topstep-combine-beta-to-vercel-and-railway` | Open until deployed acceptance evidence exists |
| Physical TPM profile | Self-hosted Pi and future live/live-credential security | TPM child tasks and hardware matrix | Deferred only for hosted Combine; tasks remain incomplete |

Implementation status and exact command evidence SHALL be appended as tasks complete; code presence alone does not change a row to verified.

## Durable Topstep onboarding slice - 2026-09-25

| Requirement | Implementation evidence | Automated evidence | Status / remaining gap |
| --- | --- | --- | --- |
| encrypted credentials and sessions | `TopstepCredential`, fenced `TopstepProviderSession`; purpose-bound envelopes and validation/reauthentication boundary | deterministic renewal/failure tests plus PostgreSQL lease/takeover tests | Software complete; Railway custody and real-provider validation open |
| discovery and attestation | generation-bound safe snapshots and exact versioned attestation | substitution and cross-tenant tests | Local only; real provider open |
| operator approval | exact tenant/integration/generation/account/attestation/cohort and purpose/case | service tests plus PostgreSQL concurrent uniqueness | Local only; full operator matrix open |
| eligibility | single typed `execution_eligibility` decision | exact allow and substitution/replacement/delete denies | Decision only; no execution enabled |
| replacement/deletion | validate-before-mutate, invalidation, suppression, erasure, terminal tombstone | rollback, idempotent deletion, and 40-case PostgreSQL race matrix | Software complete; external offboarding and restore drill open |
| architectural enforcement | order paths disabled; account metadata cannot authorize | positive/negative static fixtures | Local only; protected-host CI open |
| migrations | `fe5b6c7d8e9f` composite FKs and partial unique indexes | fresh SQLite/PostgreSQL; one head | Verified locally |
| frontend contract | masked non-repopulating key, safe selection, attestation, replacement/disconnect/delete | final build/tests pending | Implemented; verification open |

No row is Vercel, Railway, Topstep sandbox, real credential, restored-backup, or provider-order evidence. The hosted child and the deferred physical TPM work remain open.

## Durable session and restore security slice - 2026-09-25

| Requirement | Implementation | Evidence | Status |
| --- | --- | --- | --- |
| single-flight renewal | session lease owner/expiry, monotonic fence, session generation, fenced commit | prior PostgreSQL simultaneous claims/takeover; current local lease-expiry and stale-fence tests | Current PostgreSQL rerun remains open |
| provider validation | official `/api/Auth/validate`, strict `newToken`, safe classifications, current-generation reauthentication | deterministic adapter and renewal injection tests | Fake provider only |
| lifecycle precedence | replacement/revocation/deletion erase or revoke sessions and increment fences | lifecycle injection and terminal-state tests | Software verified |
| restore resurrection defense | external `HOSTED_SECURITY_EPOCH`, degraded readiness, worker suppression, revoke-by-default reconciliation | local restore tests; prior PostgreSQL epoch matrix predates latest edits | Current PostgreSQL rerun and platform restore drill open |
| stale worker/outbox defense | generation/epoch fields and centralized consumer validation | deletion/restore suppression and race assertions | Software verified; provider execution remains disabled |

The 40 PostgreSQL-named lifecycle/restore cases are invariant scenarios, not 40 separately
orchestrated concurrent interleavings. Current focused local regression is 43 passed with 399
warnings; the full backend suite is 297 passed, 67 skipped, and 7,453 warnings. Fresh SQLite and
PostgreSQL reached linear head `ff6c7d8e9f0a`; 66 PostgreSQL suites plus the restore integration test
passed after the latest fixes. The full concurrent race matrix remains open; see hosted child
verification evidence.

## Hosted Combine risk and dry-run traceability — 2026-09-29

| Requirement | Implementation/evidence | Status |
| --- | --- | --- |
| Server-owned hosted policy and consent | HostedCombineRiskPolicy/HostedCombineConsent, migration fg7d8e9f0a1b, hosted dry-run module and hosted execution delta spec | Model and policy validation exist; consent/policy route authorization and mismatch/expiry test coverage remains open |
| Durable read-only dry run and proposal isolation | HostedCombineDryRun/HostedCombineProposal; durable worker claims and fences; Topstep mutation-off guard; SQLite fixtures and architecture scan | No provider mutation path; external/provider-backed risk snapshots unavailable, so release-qualified proposals not proven |
| Deployment readiness | Vercel frontend-only and Railway API/worker artifacts, secret scanner, deployment preflight | Artifacts verified locally; no production variables/deployment; preflight fails closed without configuration |
| Regression/migration | Full backend 303 passed/68 skipped/7,420 warnings; targeted PostgreSQL policy constraints; SQLite and PostgreSQL fresh migration to fg7d8e9f0a1b | Software verification passed; warning gate and external deployment remain open |
| PostgreSQL deletion/recovery races | Existing targeted PostgreSQL tests and 40 invariant scenarios | Full per-interleaving race matrix and backup-platform restore remain open (7.4/11.4) |
