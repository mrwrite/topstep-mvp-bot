# Verification Evidence

Verified on 2026-09-24 from a Windows development host. Software and mocked-command evidence below does not constitute physical Raspberry Pi or TPM evidence.

Physical evidence remains open and is deferred as a blocker only for the owner-approved one-user Railway-hosted Trading Combine beta. It remains required for the self-hosted production profile and future live/live-credential readiness; this status change supplies no new hardware evidence.

## Automated results

| Scope | Exact command | Result | Duration / warnings / skips |
|---|---|---|---|
| Provider, envelope, rotation, recovery, migration, managed-secret, and architecture focus | `.\\venv\\Scripts\\python.exe -m pytest tests\\test_tpm_key_management.py tests\\test_key_rotation_migration.py tests\\test_key_management_architecture.py tests\\test_simulation_beta_managed_secrets.py -q` | Exit 0; 34 passed | 2.27 s; 22 warnings; 0 skipped |
| Complete backend, final | `.\\venv\\Scripts\\python.exe -m pytest -q --basetemp=.tmp\\pytest-tpm-full-final` | Exit 0; 248 passed | 544.88 s; 7,076 warnings; 21 environment-gated PostgreSQL skips |
| PostgreSQL concurrency and durable regressions | `$env:TEST_POSTGRES_URL='postgresql+psycopg2://postgres:postgres@localhost:55432/topstep_test'; .\\venv\\Scripts\\python.exe -m pytest tests\\test_key_rotation_postgres.py tests\\test_tenant_enforcement_postgres.py tests\\test_durable_execution_postgres.py tests\\test_durable_evaluation_postgres.py -q` | Exit 0; 21 passed against PostgreSQL 17 | 8.76 s; 601 warnings; 0 skipped |
| Architecture policy | `.\\venv\\Scripts\\python.exe scripts\\check_key_management_architecture.py` | Exit 0; PASS | <1 s; no warnings |
| Python compilation | `.\\venv\\Scripts\\python.exe -m compileall -q app scripts tests migrations` | Exit 0 | 0.18 s |
| Existing environment dependency consistency | `.\\venv\\Scripts\\python.exe -m pip check` | Exit 0; no broken requirements | 3.47 s |
| Clean environment dependency consistency | `.\\.tmp\\tpm-clean-venv\\Scripts\\python.exe -m pip check` | Exit 0; no broken requirements | Clean install completed in approximately 80.5 s |
| Clean configured imports | `$env:APP_ENV='test'; $env:DATABASE_URL='sqlite:///./.tmp/tpm-clean-import.sqlite'; .\\.tmp\\tpm-clean-venv\\Scripts\\python.exe -c "import app.main, app.crypto, app.key_management, app.key_rotation"` | Exit 0 | 5.41 s |
| Clean focused tests | `.\\.tmp\\tpm-clean-venv\\Scripts\\python.exe -m pytest tests\\test_tpm_key_management.py tests\\test_key_management_architecture.py -q` | Exit 0; 28 passed | 2.30 s; 19 warnings |
| Alembic graph | `.\\venv\\Scripts\\python.exe -m alembic heads` and `.\\venv\\Scripts\\python.exe -m alembic history` | Exit 0; one linear head `fd4a5b6c7d8e` | No branch heads |
| Fresh SQLite migration | `$env:DATABASE_URL='sqlite:///./.tmp/fresh-tpm-keymgmt.sqlite'; .\\venv\\Scripts\\python.exe -m alembic upgrade head` then `... alembic current` | Exit 0; current `fd4a5b6c7d8e (head)` | SQLite non-transactional-DDL notice |
| Empty PostgreSQL migration | Isolated `postgres:17` container on port 55432, followed by `alembic upgrade head` and `alembic current` with its explicit URL | Exit 0; current `fd4a5b6c7d8e (head)` | Container stopped after tests |
| Frontend clean install | `npm.cmd ci` | Exit 0; 217 packages added, 218 audited | 17.04 s; 9 total dev-inclusive advisories (1 low, 2 moderate, 6 high) |
| Frontend tests | `npm.cmd test -- --run` | Exit 0; 2 files / 2 tests passed | 29.45 s |
| Frontend production build | `npm.cmd run build` | Exit 0; 87 modules transformed | 0.981 s |
| Production dependency audit | `npm.cmd audit --omit=dev` | Exit 0; 0 vulnerabilities | No production advisory |
| Demo smoke | `.\\venv\\Scripts\\python.exe scripts\\demo_smoke.py` | Exit 0; smoke passed; live trading remained disabled | No physical broker execution |
| Parent OpenSpec strict validation | `npx.cmd --yes @fission-ai/openspec@1.3.1 validate complete-simulation-beta-security-and-operations-gates --strict` | Exit 0; valid | 2.80 s |
| Superseded AWS child strict validation | `npx.cmd --yes @fission-ai/openspec@1.3.1 validate implement-aws-kms-envelope-encryption-and-roles-anywhere --strict` | Exit 0; valid | 1.44 s on corrected run |
| Replacement child strict validation | `npx.cmd --yes @fission-ai/openspec@1.3.1 validate replace-aws-kms-with-tpm-backed-local-key-management --strict` | Exit 0; valid | 1.41 s on corrected run |
| Patch hygiene | `git -c safe.directory=C:/Users/aquin/source/repos/topstep_mvp_bot diff --check` | Exit 0 | CRLF conversion notices only |

## Initial failures and corrections

- The first focused rerun named a nonexistent `tests/test_managed_secrets.py`; it collected zero tests. The command was corrected to `tests/test_simulation_beta_managed_secrets.py`, and all 34 selected tests passed.
- The new crash-before-commit test initially failed because `pytest` was not imported. The missing import was added; the focused suite and final full suite pass.
- A complete backend attempt reached 246 passed and 21 skipped but reported two setup errors because pytest could not enumerate `C:\\Users\\aquin\\AppData\\Local\\Temp\\pytest-of-aquin`. Both affected tests passed separately with a workspace `--basetemp`; the complete suite was then rerun with that deterministic temp root and passed 248 tests.
- A first clean-import command inherited the repository `.env` and attempted unavailable PostgreSQL on localhost:5432. The corrected command set an explicit test SQLite URL and passed.
- A plain `alembic current` likewise inherited that unavailable PostgreSQL URL. The explicit fresh-SQLite command passed; PostgreSQL `current` had already passed against the isolated PostgreSQL 17 container.
- Initial sandboxed npx validation attempts for the two child changes failed with npm cache/registry `EACCES`. Both exact strict validations passed when rerun with approved package-cache/network access.
- The first frontend `npm ci` invocation lost its process handle before returning a result. The clean retry completed successfully.
- `py -3.12 -m venv` was unavailable because the Windows launcher had no registered Python 3.12. A clean environment was created with the repository interpreter instead, installed from the lock file, passed `pip check`, imports, and focused tests.

## Warning accounting

The parent pre-slice evidence recorded 5,307 backend warnings. An early TPM-slice full run recorded 7,079. The final fully passing run records 7,076, three fewer than that early run but 1,769 above the parent baseline. The increase is primarily repeated pre-existing datetime/Pydantic/SQLAlchemy warnings plus new executions of database-heavy tests. Warning enforcement is not complete and remains a release blocker.

## Evidence limitations and open gates

- This host has no Raspberry Pi, `/dev/tpmrm0`, TPM resource manager, or physical TPM. No claim is made for physical-key creation, non-exportability, persistent-handle survival, Pi reboot, container restart, upgrade, real lockout, or device-permission behavior.
- TPM command-adapter tests use deterministic fakes/mocks. Cryptography tests use software-generated RSA keys only as visibly named development/test fixtures; production rejects that provider.
- PostgreSQL verifies concurrent `SKIP LOCKED` claims, expired-claim recovery, tenant enforcement, durable execution, and durable evaluation. A database backup/restore plus replacement-TPM recovery drill was not possible and task 4.5 remains open.
- The offline recovery package workflow is implemented and tested for correct key, wrong key, and corruption. No production recovery private key was created, and no replacement-Pi ceremony occurred.
- No production database was available for authoritative Fernet inventory or migration. Envelope-only rejection is tested, but production cutover, legacy-key removal, 30-day rollback custody, and destruction approval remain open.
- `pip-audit` is not installed in either environment; `.\\venv\\Scripts\\python.exe -m pip_audit` failed with `No module named pip_audit`. `pip check` passed, but Python vulnerability auditing remains unavailable.
- Protected-host CI, warning policy, operator approvals, backup evidence, cohort policy, and all physical-hardware evidence remain open. Consequently the invite-only simulation beta is still NO-GO.

## Hardware evidence matrix

| Required evidence | Status |
|---|---|
| Physical TPM identity, firmware, attributes, persistent handle, name, and fingerprint | Not run; open |
| TPM private portion proven non-exportable | Not run; open |
| Application/container restart and Pi reboot | Not run; open |
| TPM outage, authorization failure, and lockout on hardware | Not run; open |
| Physical key-version rotation and retirement dependency proof | Not run; open |
| Restored backup recovered and rewrapped to replacement Pi TPM | Not run; open |
| Production Fernet inventory reaches zero and envelope-only cutover | Not run; open |
| Legacy and retired-key destruction approvals | Not granted; open |
