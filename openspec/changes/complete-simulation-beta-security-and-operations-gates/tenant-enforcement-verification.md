# Universal tenant-enforcement verification

## Scope

This evidence covers tasks 2.1–2.4 of the simulation-beta change. It verifies
the trusted request/job/operator context, scoped repository boundary, beta-route
migration, stream/status authorization, lifecycle isolation, architectural scan,
and PostgreSQL relationship constraints. It does not close the overall
simulation-beta gate.

## Evidence matrix

| Requirement | Evidence | Result |
|---|---|---|
| Complete resource/access inventory | `tenant-enforcement-inventory.md` and `cross-tenant-negative-matrix.md` | Pass |
| Mandatory immutable tenant context | `app/authorization.py`, `tests/test_universal_tenant_enforcement.py` | Pass |
| Scoped repository access | `app/tenant_repository.py`, repository and API negative tests | Pass |
| Verified background-job envelopes | `VerifiedTenantJob`, substitution/expiry/signature tests | Pass |
| Beta-route migration | route inventory and architectural scan | Pass |
| Streams/status/lifecycle isolation | durable API, deletion, and negative tests | Pass |
| Operator target-bound access | operator context tests and audited context creation | Pass |
| Architectural guardrails | `app/tenant_architecture.py` and fixture tests | Pass |
| Database tenant relationship constraints | `fc3f4a5b6c7d` migration and PostgreSQL tests | Pass |

## Commands and results

Focused repository/context suite:

```text
python -m pytest -q tests/test_universal_tenant_enforcement.py tests/test_tenant_repository.py
43 passed, 40 warnings, 4.24s
```

PostgreSQL constraint suite (opt-in `DURABLE_POSTGRES_TEST_URL`):

```text
python -m pytest -q tests/test_tenant_enforcement_postgres.py
3 passed, 18 warnings, 0.91s
```

Cross-tenant durable API and deletion tests passed as part of the focused
durable/security suites. The matrix covers reads, writes, commands, worker
envelopes, streams, exports, deletion, operator context, bulk operations,
aggregates, and tenant-inclusive foreign keys.

Fresh database migration evidence:

```text
DATABASE_URL=sqlite:///./.tmp/tenant-fresh.db python -m alembic upgrade head
python -m alembic current
python -m alembic heads
```

SQLite and disposable PostgreSQL 17 both reached `fc3f4a5b6c7d`; history has
one linear head. PostgreSQL constraint tests passed against the disposable
database.

The full backend suite was run twice with isolated test directories. The first
run reported 216 passed, 20 skipped, and 2 legacy compatibility failures. Both
failures were corrected without weakening isolation: public waitlist
deduplication now uses an explicit global operator port, and aggregate analytics
uses an explicit audited operator aggregate port. The affected tests were then
re-run successfully. The final run completed with **218 passed, 20 skipped,
7,043 warnings in 737.38 seconds**.

Frontend reproducibility and build:

```text
npm ci
2 frontend test files / 2 tests passed
npm run build                 PASS
npm audit --omit=dev         0 production vulnerabilities
```

The clean install reported 9 development dependency vulnerabilities (1 low, 2
moderate, 6 high); this is not included in the production-only audit result and
remains a separate quality/dependency disposition item.

## Warning disposition

The prior full-suite baseline was 6,896 warnings. The focused tenant suite
produced 40 warnings and the PostgreSQL suite 18 warnings. The full-suite run
before the compatibility corrections reported 7,004 warnings. Most are
pre-existing datetime, SQLAlchemy, and Pydantic deprecations; this slice does
not claim the warning-budget blocker is resolved. No global warning suppression
was added.

## Limitations

- PostgreSQL host CI and protected-branch evidence remain owner-controlled.
- Managed production KMS selection, clean locked-install evidence, operational
  approvals, and backup-provider purge evidence remain open blockers.
- `pip_audit` was not runnable because the module is not installed in the
  repository virtual environment; no Python audit result is claimed.
- Database row-level security was not added; application repository/context
  guards and tenant-inclusive constraints are the verified control for this
  slice.
