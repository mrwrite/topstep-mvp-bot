# Cross-Tenant Negative-Test Matrix

Evidence checkpoint: 2026-09-22. `test_universal_tenant_enforcement.py`
contains 40+ independently identified parameter cases; API, lifecycle, durable,
and PostgreSQL suites add boundary-specific evidence. Database assertions verify
that rejected requests return no foreign row, create no command/input/outbox,
and do not change the target record.

| # | Scenario | Enforcement / direct evidence | Status |
| --- | --- | --- | --- |
| 1 | user read | target tenant profile port; operator path requires exact target | Covered |
| 2 | user update | path target and operator context must match; ordinary profile is session user | Covered |
| 3 | account/integration read | repository parameter case + integration API isolation | Covered |
| 4 | integration read | repository parameter case | Covered |
| 5 | credential mutation | foreign integration resolves as absent before credential handling | Covered |
| 6 | simulation-run read | repository and API status 404 | Covered |
| 7 | command submission | cross-run durable API test; command count unchanged | Covered |
| 8 | pause/resume/stop/kill | four API cases return the same 404; no outbox/command delta | Covered |
| 9 | market-input queue | API 404 and zero market rows | Covered |
| 10 | evaluation | repository case and signed worker context | Covered |
| 11 | checkpoint access | repository case | Covered |
| 12 | lease acquisition | durable cross-tenant/fence tests plus repository case | Covered |
| 13 | order creation | repository case and stale/foreign durable authority tests | Covered |
| 14 | fill creation | repository case and fenced fill tests | Covered |
| 15 | position access | repository case | Covered |
| 16 | ledger access | repository case | Covered |
| 17 | risk-state access | repository settings and run-counter cases | Covered |
| 18 | outbox claim | system discovery only; effect requires signed tenant envelope | Covered |
| 19 | delivery acknowledgement | direct tenant column plus PostgreSQL composite-FK rejection | Covered |
| 20 | recovery attempt | signed expected tenant/run and durable cross-tenant tests | Covered |
| 21 | status polling | API 404 | Covered |
| 22 | SSE subscription | status-only endpoint performs scoped lookup and returns 404 | Covered |
| 23 | WebSocket subscription | no WebSocket route exists; architecture inventory records absence | Covered (not implemented) |
| 24 | export | existing two-tenant export test excludes Bob and secrets | Covered |
| 25 | deletion | cross-tenant execute/cancel both return identical 404; no tombstone | Covered |
| 26 | restore | offline drill reapplies tenant tombstones and resurrects no session/secret | Covered at application-drill level |
| 27 | forged job signature | envelope test | Covered |
| 28 | expired job | envelope expiry test | Covered |
| 29 | tenant-substituted payload/context | envelope expected tenant and payload-hash cases | Covered |
| 30 | missing context | repository constructor and `require_tenant` cases | Covered |
| 31 | client-supplied override | AST prohibited fixture and request-context construction rules | Covered |
| 32 | operator role mismatch | API denial and `OperatorRepository` negative | Covered |
| 33 | operator purpose mismatch | `OperatorContext` construction rejection | Covered |
| 34 | operator case mismatch | `OperatorContext` construction rejection | Covered |
| 35 | operator target mismatch | route dependency/path check plus target repository scope | Covered |
| 36 | expired operator context | construction/use rejection | Covered |
| 37 | bulk update | SQLite and PostgreSQL repository tests; zero rows changed | Covered |
| 38 | bulk delete | SQLite and PostgreSQL repository tests; zero rows deleted | Covered |
| 39 | aggregate leakage | tenant count returns zero for foreign-only rows | Covered |
| 40 | pagination/count leakage | tenant list/count return empty/zero | Covered |
| 41 | job type substitution | signed-envelope case | Covered |
| 42 | job purpose substitution | signed-envelope case | Covered |
| 43 | job issuer substitution | signed-envelope case | Covered |
| 44 | job environment substitution | signed-envelope case | Covered |
| 45 | job actor substitution | signed-envelope case | Covered |
| 46 | cross-tenant revocation relationship | PostgreSQL composite-FK rejection | Covered |
| 47 | cross-tenant dirty/new ORM flush | session `before_flush` rejection and unchanged target | Covered |
| 48 | direct ORM reintroduction | allowed/prohibited AST fixtures and full request-module scan | Covered |

Timing equivalence is minimized through repository-scoped lookup followed by the
same not-found response. This suite does not claim statistically proven constant
time. Logs contain correlation, safe actor/tenant identifiers, and failure
classification; they do not contain credentials, tokens, job signatures, or
unrestricted configurations.
