# Verification evidence

Date: 2026-09-24. Host: Windows development workstation. This is local software evidence only.

## Completed checks

| Scope | Command | Result |
|---|---|---|
| Hosted/TPM key provider focus | `.\\venv\\Scripts\\python.exe -m pytest tests\\test_railway_key_management.py tests\\test_tpm_key_management.py tests\\test_key_management_architecture.py -q --basetemp=.tmp\\pytest-hosted-key-rerun` | Exit 0; 35 passed in 1.72 s; no warning summary |
| Hosted onboarding/provider regression focus | `.\\venv\\Scripts\\python.exe -m pytest tests\\test_railway_key_management.py tests\\test_topstep_hosted_onboarding.py tests\\test_tpm_key_management.py tests\\test_key_management_architecture.py tests\\test_phase2_integrations.py -q --basetemp=.tmp\\pytest-hosted-final` | Exit 0; 43 passed in 23.24 s; 117 warnings; 0 skipped |
| Architecture enforcement | `.\\venv\\Scripts\\python.exe scripts\\check_key_management_architecture.py` | Exit 0; PASS |
| Compilation | `.\\venv\\Scripts\\python.exe -m compileall -q app scripts tests` | Exit 0 |
| Patch hygiene | `git -c safe.directory=C:/Users/aquin/source/repos/topstep_mvp_bot diff --check` | Exit 0; CRLF notices only |

The initial hosted-provider focused run had 34 passes and one failure because the test expected `key_unavailable`; the envelope policy correctly rejected the unapproved version earlier as `unsupported_policy`. The assertion was corrected to the stronger fail-closed classification, after which all selected tests passed.

## Official-document review

Current ProjectX documentation was reviewed for login-key authentication, 24-hour sessions and validation, active-account search, `live: false` contract/history selection, unique order `customTag`, order placement, order search, cancellation, and rate limits. This supports safe authentication/account-discovery hardening and the design contract. It does not by itself prove account type, deployment behavior, provider idempotency under timeout, or a safe real-order acceptance result; those implementation/evidence tasks remain open.

## Evidence deliberately not claimed

- No Vercel project, preview, production build, HTTPS response, CSP, origin, or bundle evidence.
- No Railway project, API, worker, PostgreSQL, Redis, migration, backup/restore, restart, heartbeat, or secret-variable evidence.
- No tester username/API key was supplied or stored; no Topstep authentication/account response was obtained.
- No Trading Combine ownership, attestation, administrator account approval, provider dry run, or revocation evidence.
- No provider order was submitted. There is no owner authorization for an order in this evidence.
- No Express Funded, Live Funded, live brokerage, or physical TPM claim.
- Full backend/frontend/PostgreSQL/dependency/warning verification has not yet been rerun for this child.

Mocked HTTP tests prove only request shape, safe metadata projection, exact approved-ID selection, name non-authorization, and error redaction. Software RSA/AES tests prove envelope behavior, not Railway secret custody or TPM properties.

## Durable onboarding, approval, and deletion slice - 2026-09-25

This section is local software and disposable-database evidence. Fake provider credentials/tokens are
fixed test strings. No real Topstep, Vercel, Railway, account, deployment, dry-run, or order action was
performed.

| Scope | Exact command | Result |
| --- | --- | --- |
| Durable workflow focus | `.\venv\Scripts\python.exe -m pytest tests\test_topstep_durable_onboarding.py -q --basetemp=.tmp\pytest-topstep-operator-final` | Exit 0; 8 passed; 120 warnings; 33.65 s; 0 skipped |
| Hosted/architecture focus | `.\venv\Scripts\python.exe -m pytest tests\test_topstep_durable_onboarding.py tests\test_topstep_hosted_onboarding.py tests\test_railway_key_management.py tests\test_topstep_onboarding_architecture.py -q --basetemp=.tmp\pytest-topstep-after-version` | Exit 0; 23 passed; 90 warnings; 24.57 s; 0 skipped |
| PostgreSQL constraints/race | `DURABLE_POSTGRES_TEST_URL=<redacted-local-url> .\venv\Scripts\python.exe -m pytest tests\test_topstep_onboarding_postgres.py -q --basetemp=.tmp\pytest-topstep-pg-final2` | Exit 0; 2 passed; 14 warnings; 0.73 s; 0 skipped |
| Full backend | `.\venv\Scripts\python.exe -m pytest tests -q --basetemp=.tmp\pytest-full-topstep-final` | Exit 0; 273 passed; 23 skipped; 7,199 warnings; 588.15 s |
| Post-correction route/workflow regression | `.\venv\Scripts\python.exe -m pytest <live-context case> <integration CRUD case> tests\test_topstep_durable_onboarding.py -q --basetemp=.tmp\pytest-topstep-final-correction` | Exit 0; 10 passed; 263 warnings; 39.75 s |
| Fresh PostgreSQL 17 | `alembic upgrade head && alembic current && alembic heads` against disposable `postgres:17-alpine` | Exit 0; empty database reached sole head `fe5b6c7d8e9f` |
| Fresh SQLite | same Alembic commands against `.tmp/topstep-alembic-final.db` | Exit 0; empty database reached sole head `fe5b6c7d8e9f` |
| Architecture | `.\venv\Scripts\python.exe scripts\check_key_management_architecture.py` and `scripts\check_topstep_onboarding_architecture.py` | Exit 0; both PASS |
| Python environment | `python -m pip check`; `python -m pip_audit`; `python -m compileall -q app scripts tests migrations`; configured imports | pip check/compile/import exit 0; `pip_audit` unavailable (`No module named pip_audit`) |
| Frontend clean install | `npm.cmd ci` | Exit 0; 217 packages; all-dependency audit during install reported 9 findings (1 low, 2 moderate, 6 high), all in development dependency scope |
| Frontend tests | `npm.cmd test -- --run --pool=threads --maxWorkers=1` | Exit 0; 2 files, 3 tests passed; 3.74 s |
| Frontend production build/audit | `npm.cmd run build`; `npm.cmd audit --omit=dev` | Exit 0; 87 modules; 742 ms; 0 production vulnerabilities |
| Bundle secret scan | `rg` for deterministic credential/token fixture strings under `frontend/dist` | Exit 0 wrapper; no matches |
| Demo/live rejection | `.\venv\Scripts\python.exe scripts\demo_smoke.py` | Exit 0; paper seed/order/status/reset passed; live false |
| Strict OpenSpec | `npx.cmd --yes @fission-ai/openspec@1.3.1 validate <parent|TPM child|hosted child> --strict` | Exit 0; all three valid |
| Patch hygiene | `git -c safe.directory=C:/Users/aquin/source/repos/topstep_mvp_bot diff --check` | Exit 0; line-ending notices only |

The prior full-backend baseline was 248 passed, 21 skipped, and 7,076 warnings. The current full run
is 273 passed, 23 skipped, and 7,199 warnings: 25 additional passes, 2 additional environment-gated
skips, and 123 additional warnings. The warning increase is primarily the new SQLite model fixtures
triggering the repository's existing SQLAlchemy `datetime.utcnow` deprecation; the unresolved warning
budget remains a parent release blocker.

Initial corrections were retained as evidence: the first combined focused run exposed an adapter
response compatibility mismatch and was corrected without weakening the safe persisted projection.
The first new frontend test run exposed missing test cleanup and an unstable mocked hook that caused
duplicate DOM and orphaned Vitest workers; cleanup and stable function identities corrected it. A
subsequent Windows Node worker allocation failure was rerun with one worker after the orphaned test
processes were terminated. Final frontend evidence is green.

The first post-hardening route regression found that the initial active-integration partial index also
counted an explicitly inactive legacy paper fixture. The predicate was corrected to exclude
`inactive`, `disabled`, and terminal `deleted` rows while still preventing two executable Topstep
integrations. The affected route/workflow regression then passed 10 tests, and the corrected migration
was rerun from empty on PostgreSQL 17 before final evidence was recorded.

The PostgreSQL tests prove the composite tenant foreign key rejects a credential attached to another
tenant's integration and the partial unique approval index lets exactly one of two simultaneous
different-account approvals commit. They do not constitute the complete requested deletion/recovery
race matrix; that task remains open. Session expiry now denies eligibility and enters durable leased
renewal; current-token validation and explicit-invalid-token reauthentication have deterministic
fake-provider coverage. Restored-backup revocation against a real PostgreSQL restore, external key
revocation, deployment, real-provider validation, dry run, and any provider order remain unexecuted.

## Durable session and restore-safety continuation — 2026-09-29

All tests used deterministic fake providers and local SQLite unless otherwise stated. No real Topstep
credentials, provider orders, external deployment, or external backup restore were used.

| Scope | Exact command | Result |
| --- | --- | --- |
| Session, onboarding, tenant, architecture, durable regression | `\.\venv\Scripts\python.exe -m pytest tests\test_topstep_session_restore_security.py tests\test_topstep_durable_onboarding.py tests\test_topstep_hosted_onboarding.py tests\test_topstep_onboarding_architecture.py tests\test_durable_simulation.py -q --tb=short --basetemp=.tmp\pytest-session-restore-final -o cache_dir=.tmp\pytest-session-restore-final-cache` | Exit 0; 43 passed; 399 warnings; 0 skipped; 134.77 s |
| Full backend | `\.\venv\Scripts\python.exe -m pytest tests -q --tb=short --basetemp=.tmp\pytest-hosted-session-full -o cache_dir=.tmp\pytest-hosted-session-full-cache` | Exit 0; 297 passed; 67 skipped; 7,453 warnings; 722.98 s |
| Edge-case correction rerun | `\.\venv\Scripts\python.exe -m pytest tests\test_topstep_session_restore_security.py::test_restore_reconciliation_rejects_expired_operator_context tests\test_topstep_session_restore_security.py::test_renewal_owner_cannot_commit_after_lease_expiry_without_takeover tests\test_topstep_session_restore_security.py::test_simulation_run_binds_topstep_generation_and_epoch_from_database -q --basetemp=.tmp\pytest-session-edge-rerun -o cache_dir=.tmp\pytest-session-edge-rerun-cache` | Exit 0; 3 passed; 36 warnings; 0 skipped; 11.82 s |
| Initial focused attempt | `\.\venv\Scripts\python.exe -m pytest tests\test_topstep_session_restore_security.py -x -vv --tb=short --basetemp=.tmp\pytest-session-isolate -o cache_dir=.tmp\pytest-session-isolate-cache` | Exit 1; exposed tenant-repository misuse while locking global User; corrected with tenant-keyed `lock_tenant_owner()`; subsequent 43-test suite passed |
| Architectural enforcement | `\.\venv\Scripts\python.exe scripts\check_topstep_onboarding_architecture.py` | Exit 0; PASS |
| Compilation | `\.\venv\Scripts\python.exe -m compileall -q app scripts tests migrations` | Exit 0 |
| Dependency consistency/audit | `\.\venv\Scripts\python.exe -m pip check`; `\.\venv\Scripts\python.exe -m pip_audit` | `pip check` exit 0 (no broken requirements); `pip_audit` unavailable (module not installed), exit 1 |
| Fresh SQLite migration | `$env:DATABASE_URL='sqlite:///./.tmp/restore-safety.sqlite'; .\venv\Scripts\alembic.exe upgrade head` | Exit 0; empty SQLite database reached `ff6c7d8e9f0a` |
| Alembic state/history | `$env:DATABASE_URL='sqlite:///./.tmp/restore-safety.sqlite'; .\venv\Scripts\alembic.exe current; .\venv\Scripts\alembic.exe heads; .\venv\Scripts\alembic.exe history --rev-range=-3:` | Exit 0; current and only head `ff6c7d8e9f0a`; linear predecessor chain |
| Frontend tests | `npm.cmd test -- --run --pool=threads --maxWorkers=1` from `frontend` | Exit 0; 2 files, 3 passed; 0 skipped; 30.81 s |
| Strict OpenSpec | `npx.cmd --yes @fission-ai/openspec@1.3.1 validate <change> --strict` for hosted child, parent, and deferred TPM child | Exit 0; all three valid |
| Patch hygiene | `git -c safe.directory=C:/Users/aquin/source/repos/topstep_mvp_bot diff --check` | Exit 0; only existing LF-to-CRLF notices |
| PostgreSQL service availability | `docker ps` | Exit 1; Docker Desktop Linux-engine named pipe absent; current PostgreSQL race/migration suite could not be rerun |

The expired-operator test initially tried to construct an invalid `OperatorContext`; its constructor
correctly rejected it. The corrected test creates a valid context then simulates staleness before
service entry, proving the service-level check. An initial Alembic history invocation used invalid
PowerShell argument parsing; `--rev-range=-3:` corrected it. Warning accounting is scoped: the
previous full-backend baseline is 7,199 warnings; this continuation's focused run reports 399
warnings (primarily existing SQLAlchemy `datetime.utcnow` defaults plus Pydantic/declarative
deprecations). The suites differ in scope, so this is not a full-suite warning delta. Current full
backend verification and warning-budget reconciliation remain open. SQLite migration emitted one
Pydantic config warning; frontend tests had no warning summary.

The earlier PostgreSQL 17 migration and 44-test suite predate the latest code/schema edits. It included
two actual concurrent renewal lease/takeover tests and 40 named fail-closed lifecycle/restore invariant
cases; those cases were not 40 separately orchestrated races. The current PostgreSQL migration,
deletion test, restore test, and full race matrix remain open because Docker is unavailable. SQLite
does not prove PostgreSQL locking, isolation, or `SKIP LOCKED`. No Railway restore, provider call,
deployment, provider order, or dry run was performed.

## PostgreSQL availability restored — 2026-09-29 follow-up

A disposable PostgreSQL 17 container was started with no persistent volume and a loopback-only port.
Separate databases were used for fresh migration, shared race suites, and the destructive restore
fixture. No real user/provider data was used.

| Scope | Exact command | Result |
| --- | --- | --- |
| PostgreSQL readiness | `docker exec topstep-session-restore-check-20260929 pg_isready -U topstep_test -d topstep_test` | Exit 0; accepting connections |
| Fresh PostgreSQL migration | `$env:DATABASE_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_test'; .\venv\Scripts\alembic.exe upgrade head` | Exit 0; empty PostgreSQL 17 database reached `ff6c7d8e9f0a`; 5.79 s; one Pydantic config warning |
| Fresh race-database migration | `$env:DATABASE_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_race_test'; .\venv\Scripts\alembic.exe upgrade head` | Exit 0; empty PostgreSQL database reached `ff6c7d8e9f0a`; 3.34 s; one Pydantic config warning |
| Alembic state/history | `$env:DATABASE_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_test'; .\venv\Scripts\alembic.exe current; .\venv\Scripts\alembic.exe heads; .\venv\Scripts\alembic.exe history --rev-range=-3:` | Exit 0; current and only head `ff6c7d8e9f0a`; linear predecessor chain; 5.53 s; one Pydantic config warning |
| PostgreSQL execution, evaluation, key rotation, tenant, onboarding, renewal/deletion suites | `$env:DURABLE_POSTGRES_TEST_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_race_test'; .\venv\Scripts\python.exe -m pytest tests\test_durable_evaluation_postgres.py tests\test_durable_execution_postgres.py tests\test_key_rotation_postgres.py tests\test_topstep_session_race_matrix_postgres.py tests\test_topstep_onboarding_postgres.py tests\test_tenant_enforcement_postgres.py -q --tb=short --basetemp=.tmp\pytest-all-postgres -o cache_dir=.tmp\pytest-all-postgres-cache` | Exit 0; 66 passed; 905 warnings; 0 skipped; 23.03 s |
| PostgreSQL restore reconciliation | `$env:HOSTED_RESTORE_POSTGRES_TEST_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_restore_test3'; .\venv\Scripts\python.exe -m pytest tests\test_topstep_restore_postgres.py -q --tb=short --basetemp=.tmp\pytest-pg-restore-final3 -o cache_dir=.tmp\pytest-pg-restore-final3-cache` | Exit 0; 1 passed; 16 warnings; 0 skipped; 4.68 s |
| Accepted-command deletion regression | `$env:DURABLE_POSTGRES_TEST_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_race_test'; .\venv\Scripts\python.exe -m pytest tests\test_topstep_session_race_matrix_postgres.py::test_postgres_delete_fences_renewal_kills_run_and_terminally_suppresses_work -q --tb=short --basetemp=.tmp\pytest-pg-delete-fix -o cache_dir=.tmp\pytest-pg-delete-fix-cache` | Exit 0; 1 passed; 19 warnings; 0 skipped; 2.35 s |
| Final focused regression after command-suppression fix | `\.\venv\Scripts\python.exe -m pytest tests\test_topstep_session_restore_security.py tests\test_topstep_durable_onboarding.py tests\test_topstep_hosted_onboarding.py tests\test_topstep_onboarding_architecture.py tests\test_durable_simulation.py -q --tb=short --basetemp=.tmp\pytest-session-restore-postgres-fix -o cache_dir=.tmp\pytest-session-restore-postgres-fix-cache` | Exit 0; 43 passed; 399 warnings; 0 skipped; 184.58 s |

The first PostgreSQL race-suite attempt failed 1 test (44 passed): deletion left an `accepted`
command uncancelled. `_suppress_execution` now terminally cancels `pending`, `accepted`, `claimed`,
and `processing` commands; the focused regression and full 66-test PostgreSQL suite then passed.
The restore integration initially expected `security_epoch_status` to raise on rollback, while its
contract is a safe `rollback_rejected` status; the assertion now verifies that classification. Its
first database setup used `drop_all`, which is unsafe and fails on the existing users/integrations FK
cycle when reused. The test now refuses non-empty databases and performs no destructive reset; a
fresh dedicated database passed. This verifies seeded stale database-state reconciliation, not an
actual `pg_restore` operation or Railway backup-platform recovery.

Failure commands and outcomes: the initial combined race/onboarding command above first returned
exit 1 with 44 passed, 1 failed, 309 warnings in 11.49 s due to the accepted-command omission. The
first restore attempt was `$env:HOSTED_RESTORE_POSTGRES_TEST_URL='postgresql+psycopg2://topstep_test@127.0.0.1:55432/topstep_restore_test'; .\venv\Scripts\python.exe -m pytest tests\test_topstep_restore_postgres.py -q --tb=short --basetemp=.tmp\pytest-pg-restore-final -o cache_dir=.tmp\pytest-pg-restore-final-cache`; it exited 1 (0 passed, 1 failed, 16 warnings, 5.37 s) because the test expected an exception rather than the returned safe epoch classification. The immediate corrected rerun against the already-used database exited 1 (0 passed, 1 failed, 4 warnings, 3.85 s) because `drop_all` could not sort the existing users/integrations FK cycle. No application tables were dropped by that failed sort. The expectation was corrected, reset was removed in favor of an empty-database guard, and a fresh isolated database passed as recorded above.

PostgreSQL evidence closes task 8.2 (fresh linear migration plus current targeted durable,
concurrency, fencing, deletion, and restore tests). Tasks 7.4 and 11.4 remain open: 40 parameterized
matrix cases assert fail-closed invariants, but they are not 40 separately orchestrated concurrent
interleavings; only renewal claim/takeover and approval uniqueness have actual two-thread concurrency
tests, and external backup restoration remains untested. No provider call or order was made.

## Hosted risk-policy and dry-run readiness — 2026-09-29

No Vercel/Railway deployment, real Topstep credentials, provider network call/order, or backup-platform
restore was performed. PostgreSQL 17 was disposable and loopback-only; test fixtures were synthetic.

| Check | Exact command | Result |
| --- | --- | --- |
| Fresh PostgreSQL migration | DATABASE_URL=postgresql+psycopg2://topstep_test@127.0.0.1:55433/topstep_dryrun_final2; alembic upgrade head; current; heads | Exit 0; empty database at fg7d8e9f0a1b, one head; 13.1 s overall; Pydantic configuration warning |
| Fresh SQLite migration/history | DATABASE_URL=sqlite:///./.tmp/hosted-risk-postfix-final.sqlite; alembic upgrade head; current; heads; history --rev-range=-3: | Exit 0; fg7d8e9f0a1b current and only head; linear history; 16.3 s; one Pydantic configuration warning |
| PostgreSQL policy constraints and focused tests | HOSTED_POLICY_POSTGRES_TEST_URL=postgresql+psycopg2://topstep_test@127.0.0.1:55433/topstep_dryrun_final2; pytest tests/test_hosted_combine_policy_postgres.py tests/test_hosted_combine_dryrun.py -q --tb=short --basetemp=.tmp/hosted-policy-final | Exit 0; 7 passed, 14 warnings, 0 skipped, 36.83 s. PostgreSQL exercised active-policy uniqueness and tenant-bound FK rejection; remaining focused fixtures used SQLite. Not the full PostgreSQL race matrix. |
| Full post-fix backend | DATABASE_URL=sqlite:///./.tmp/hosted-combine-risk-final.sqlite; pytest tests -q --tb=short -p no:cacheprovider --basetemp=.tmp/pytest-hosted-risk-postfix-full | Exit 0; 303 passed, 68 skipped, 7,420 warnings, 1,399.33 s. Prior full run: 297 passed, 67 skipped, 7,453 warnings. Warning count fell by 33 but warning governance remains unresolved. |
| Clean frontend install | npm.cmd ci in frontend | Exit 0; 217 packages; full tree reported 10 vulnerabilities (1 low, 3 moderate, 6 high); no automatic fixes applied. |
| Frontend tests | npm.cmd test -- --run --pool=threads --maxWorkers=1 in frontend | Exit 0; 2 files, 3 tests passed, no warning summary, 67.51 s. Initial run concurrent with backend timed out starting worker; serial rerun after backend passed. |
| Frontend build | npm.cmd run build in frontend | Exit 0; Vite 7.1.12, 87 modules, 4.47 s; build artifact only, not deployment. |
| Production dependency audit | npm.cmd audit --omit=dev in frontend | Exit 0; 0 production vulnerabilities. |
| Frontend secret scan | python scripts/check_frontend_secret_scan.py | Exit 0; configured private values absent. No production API URL was configured, so no such value was verified in the bundle. |
| Deployment preflight | python scripts/hosted_beta_preflight.py --json | Expected exit 1; 40 checks failed due missing production variables, origins, policy/database, and secrets; no values were printed. Not a valid deployed preflight pass. |
| Architecture checks | python scripts/check_hosted_combine_safety.py; check_key_management_architecture.py; check_topstep_onboarding_architecture.py | All exit 0 and PASS. |
| Compile/import | python -m compileall -q app scripts tests; import app.main, app.worker_entrypoint, app.hosted_combine_dryrun, app.hosted_combine_routes with verified PostgreSQL DATABASE_URL | Exit 0; compileall quiet; imports passed; one Pydantic configuration warning. First attempt used default localhost:5432 and failed; explicit DB URL corrected it. |
| Python dependencies | python -m pip check; python -m pip_audit | pip check exit 0, no broken requirements. pip_audit unavailable (module not installed), exit 1. |
| Demo | DATABASE_URL=sqlite:///./.tmp/hosted-demo-smoke.sqlite; python scripts/demo_smoke.py | Exit 0; paper-only seed/status/reset passed, live=false; no Topstep provider or live order. Synthetic demo identifiers only. |
| Diff check | git diff --check | Exit 0, no whitespace errors; Git emitted LF-to-CRLF working-tree notices. |
| Strict OpenSpec | npx.cmd --yes @fission-ai/openspec@1.3.1 validate --strict for parent, deferred TPM child, hosted child | Exit 0; all three valid. openspec.cmd was initially not on PATH; pinned npx CLI succeeded. |

The first full post-fix run included a SQLite naive/aware datetime assertion failure introduced by a
new test; the assertion was made timezone-safe, focused tests passed, then the complete backend suite
passed. Current limitations: risk-policy and consent endpoint authorization/mismatch/expiry tests,
provider-backed read-only account/market/order/position/P&L/reconciliation evidence, production
preflight, exact preview-origin verification, deployment, full individually orchestrated PostgreSQL
race matrix (7.4/11.4), backup-platform restore, real credentials, and owner-selected risk values are
open. Provider mutation remains disabled; dry-run proposals cannot authorize execution.
