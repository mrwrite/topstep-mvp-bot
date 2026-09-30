# Durable execution failure-injection matrix

Evidence date: 2026-07-29. “Covered” means an automated test asserts committed
database state. PostgreSQL rows ran against PostgreSQL 17; the process drill
terminates real Python worker processes and reconnects to the same database.

| # | Failure / competition | Direct database evidence | Status |
| --- | --- | --- | --- |
| 1 | concurrent same-key start | PG `test_postgres_same_start_key_returns_one_run_and_command` | Covered |
| 2 | concurrent different-key same-scope start | PG `test_postgres_concurrent_scope_has_one_authoritative_run` | Covered |
| 3 | duplicate pause | SQLite parameter test and PG pause race | Covered |
| 4 | duplicate resume | SQLite idempotency parameter test | Covered |
| 5 | duplicate stop | SQLite idempotency parameter test | Covered |
| 6 | duplicate kill | durable kill idempotency test | Covered |
| 7 | crash before authoritative commit | eight-stage rollback parameterization | Covered |
| 8 | crash after state/effect commit before outbox processing | restart drill leaves committed outbox recoverable; outbox claim test | Covered |
| 9 | consumer effects before acknowledgement | effect and acknowledgement co-commit; interrupted PG consumption leaves neither committed | Covered |
| 10 | crash while writing checkpoint | `after_checkpoint` injection rolls back checkpoint and effects | Covered |
| 11 | crash immediately after checkpoint commit | real process exits after first committed input; replacement reconciles | Covered |
| 12 | lease expiration | lease-expiry focused and process drill | Covered |
| 13 | lease takeover | focused fence test and process drill fence advance | Covered |
| 14 | stale checkpoint write | stale-owner checkpoint test | Covered |
| 15 | stale simulated-order write | stale-owner order test and whole-workflow stale fence test | Covered |
| 16 | stale simulated-fill write | shared fence guard plus whole-workflow stale fence test | Covered |
| 17 | stale state transition | compare-and-set stale transition test | Covered |
| 18 | restart while Starting | interrupted-state recovery test | Covered |
| 19 | restart while Running | interrupted-state recovery plus real process drill | Covered |
| 20 | restart while Pausing | interrupted-state recovery test | Covered |
| 21 | restart while Stopping / Recovering | parameterized interrupted-state recovery tests | Covered |
| 22 | database interruption during heartbeat | PG backend termination; renewal not committed | Covered |
| 23 | database interruption during command | PG backend termination; command/state not committed | Covered |
| 24 | database interruption during market/outbox | PG backend termination; no economic or delivery effect committed | Covered |
| 25 | kill while Running | API/direct kill and recovery matrix | Covered |
| 26 | kill while Pausing | parameterized kill/recovery test | Covered |
| 27 | kill while Recovering | parameterized kill/recovery test | Covered |
| 28 | kill immediately before takeover | terminal kill prevents recovery candidate/acquisition | Covered |
| 29 | expired worker returns after kill | stale returned-owner test | Covered |
| 30 | duplicate outbox delivery | consumer/event unique outcome test | Covered |
| 31 | poison event reaches retry limit | bounded retry/terminal test | Covered |
| 32 | forged or invalid tenant job | signed job-envelope negative tests | Covered |
| 33 | cross-tenant run control/input | service, HTTP, and market workflow negative tests | Covered |
| 34 | invalid state transition | state-machine tests | Covered |
| 35 | configuration mismatch during recovery | mismatch test | Covered |
| 36 | strategy-version mismatch during recovery | mismatch test | Covered |
| 37 | corrupt/unreconcilable checkpoint | digest corruption and financial-drift tests | Covered |
| 38 | stale/duplicate market input after recovery | post-recovery stale/duplicate test | Covered |
| 39 | no duplicate evaluations/orders after restart | duplicate worker PG test and process drill | Covered |
| 40 | no duplicate fills/fees/ledger after restart | process drill exact counts and unique identities | Covered |
| 41 | position/risk counters consistent after restart | checkpoint reconciliation tests and process drill | Covered |
| 42 | kill survives complete process restart | process drill killed-run restart with zero effects | Covered |

## Kill-boundary evidence

PostgreSQL parameterization races kill at fence validation, market
classification, evaluation, before/after order intent, after fill, after ledger,
and after checkpoint. The run-row lock establishes a total transaction order.
Each case ends Killed with one complete pre-kill economic transaction and zero
partial or later effects. Separate kill-first tests produce zero effects.

## Real process evidence

`scripts/durable_simulation_restart_drill.py`:

1. commits deterministic input one in a child worker;
2. lets the lease expire;
3. terminates a replacement worker with `os._exit(91)` after constructing the
   next checkpoint but before commit;
4. launches another process which takes a higher fence, reconciles, and commits;
5. redelivers the same input without duplication; and
6. restarts a killed run and verifies zero evaluations, orders, fills, ledger
   entries, or risk increments.

Machine and human evidence are retained in `evidence/`.
