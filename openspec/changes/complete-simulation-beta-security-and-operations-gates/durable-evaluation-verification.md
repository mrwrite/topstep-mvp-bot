# Durable evaluation and recovery verification

Evidence date: 2026-07-29. PostgreSQL 17 ran in the disposable
`topstep-durable-postgres` container and was stopped after verification.

| Command | Exit | Result / duration |
| --- | ---: | --- |
| `.\venv\Scripts\python.exe -m pytest -q --basetemp .tmp\full-suite\basetemp2` | 0 | 175 passed, 17 skipped, 6,896 warnings, 530.80s |
| `$env:DURABLE_POSTGRES_TEST_URL=...; .\venv\Scripts\python.exe -m pytest tests\test_durable_execution_postgres.py tests\test_durable_evaluation_postgres.py -q --basetemp .tmp\pg-final` | 0 | 17 passed, 574 warnings, 8.52s |
| `$env:DURABLE_RESTART_DRILL_DATABASE_URL=...; .\venv\Scripts\python.exe scripts\durable_simulation_restart_drill.py --output-dir openspec\changes\complete-simulation-beta-security-and-operations-gates\evidence` | 0 | PASS; controlled child exit 91, fence takeover, exact counts, killed restart; 27.8s |
| `$env:DATABASE_URL=.../durable_migration_test; .\venv\Scripts\python.exe -m alembic upgrade head` | 0 | fresh PostgreSQL 17 database reached `fb2e3f4a5b6c` |
| `.\venv\Scripts\python.exe -m alembic current/heads/history` with the same URL | 0 | one current linear head, complete history |
| `.\venv\Scripts\python.exe -m pytest tests\test_phase6_production_readiness.py::test_fresh_database_can_upgrade_to_alembic_head -q --basetemp .tmp\pytest-migration-slice` | 0 | 1 passed, 4 warnings, 6.49s |
| `.\venv\Scripts\python.exe -m pip check` | 0 | no broken requirements |
| `.\venv\Scripts\python.exe -m compileall -q app scripts migrations` | 0 | passed |
| configured `python -c "import app.main, app.simulation_evaluation, app.simulation_worker"` | 0 | `imports-ok` |
| `.\venv\Scripts\python.exe scripts\demo_smoke.py` | 0 | paper-only seed/status/manual/reset passed; live disabled |
| `npm.cmd test -- --run` in `frontend` | 0 | 2 files / 2 tests passed, 4.98s |
| `npm.cmd run build` in `frontend` | 0 | 87 modules, 1.72s |
| `npm.cmd audit --omit=dev` in `frontend` | 0 | 0 vulnerabilities |
| `openspec validate complete-simulation-beta-security-and-operations-gates --strict` | 0 | valid |
| `git -c safe.directory=... diff --check` | 0 | passed; informational LF/CRLF warnings only |

The 17 full-suite skips are the opt-in PostgreSQL modules (3 existing control
concurrency cases and 14 new evaluation/recovery cases). They were run
explicitly in the second row and all 17 passed.

## Warning impact

The previous full-suite count was 6,085. The final count is 6,896 (+811) after
adding 30 database-heavy tests. New durable modules use aware UTC. The focused
evaluation suite emitted warnings from existing `datetime.utcnow` SQLAlchemy
model defaults and tenant/observability code; replacing risk-service UTC calls
removed 28 warnings from the initial focused evaluation run. No global filter
was added. The repository warning-budget task remains open.

## Initial failures and corrections

- The first combined regression run was 90 passed / 1 failed / 4,020 warnings:
  a legacy recovery fixture named a nonexistent market boundary. It was changed
  to a valid no-market checkpoint; the focused correction passed and the final
  full suite is green.
- The first restart-drill invocation could not import `app`; repository-root
  bootstrapping was added. The next exposed a detached ORM identifier and the
  next correctly rejected a duplicate process with a different active owner.
  The drill now reuses the active owner for duplicate delivery and passes.
- The first SQLite migration test could not access the host pytest temp root.
  Re-running with the workspace-local `--basetemp` passed.
- The first import check inherited a `.env` PostgreSQL URL on unavailable port
  5432. Re-running with `ALLOW_CREATE_ALL=false` and the verified disposable
  PostgreSQL URL passed. This was an environment correction, not a database
  fallback.
- Strict OpenSpec initially rejected a wrapped requirement whose first line
  lacked normative language. The requirement was corrected and strict
  validation passed.
- `python -m pip_audit -r requirements.lock` was attempted but not run because
  `pip_audit` is absent from the current locked environment. Task 6.5 remains
  open; no audit result is claimed.
