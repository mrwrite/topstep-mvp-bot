# Durable simulation evaluation and recovery inventory

Inventory date: 2026-07-29. This inventory precedes the evaluation/recovery
implementation slice. “Automated” means work initiated by a durable worker rather
than a request handler or the manual paper-order endpoint.

| Area / entry point | Current authority and tenant source | Durable state / transaction boundary | Recovery behavior | Required migration |
| --- | --- | --- | --- | --- |
| `POST /scheduler/bot-sessions` | Authenticated HTTP user; handler also calls `process_run` | Run/command/outbox are durable, but HTTP advances Starting to Running | Startup recovery can acquire the lease later | Persist only the command in HTTP; worker alone advances execution state |
| `POST /scheduler/stop-bot` | Authenticated HTTP user; handler calls `process_run` | Durable stop command, then request-owned transition | Worker can finish an interrupted stop | Persist only the command; worker reaches a safe checkpoint and Stopped |
| `POST /simulation-runs/{id}/commands/{name}` | Authenticated HTTP user; tenant derived server-side | Durable command, but request advances pause/resume/stop | Worker recovery is available after request failure | Remove request-owned `process_run`; return accepted durable command state |
| `POST /risk/kill-switches` | Authenticated HTTP user | Kill-switch and run kill commit durably | Kill survives database/application sessions | Preserve synchronous durable kill because it is lease-independent safety intent |
| `GET /scheduler/run-bot` | Authenticated status-only SSE | Reads run row; no evaluation mutation | Reconnect does not own execution | Retain status-only compatibility; remove secret-bearing `print` helper |
| `simulation_worker.recovery_cycle` | Signed `VerifiedTenantJob` created from persisted tenant/run/event | Recovers expired runs and consumes outbox | Periodic/startup cycle | Extend to claim persisted market input and execute evaluation |
| `scheduler.fetch_price_data` | TopstepX adapter/session token | No durable input identity; request/process memory only | None | Do not use for hosted simulation; isolate as unsupported legacy provider helper |
| `strategy_engine.record_strategy_signal` | Caller-provided config; direct ORM | Commits signal and analytics internally | No deterministic evaluation identity | Automated flow MUST use a non-committing, fenced evaluator with a unique identity |
| `paper_execution.execute_paper_order` | Authenticated manual endpoint/caller intent | Multiple internal commits across risk/order/fill/ledger | Idempotency only; no run fence | Preserve for manual paper; automated flow MUST use a fenced atomic workflow |
| `risk_service.evaluate_order_intent` | Caller-provided intent | Flushes allowed decision but commits rejected decision | No run/checkpoint reconciliation | Automated flow MUST evaluate in its authoritative transaction and preserve denial evidence |
| `PaperOrder` / `PaperFill` | Manual or durable helper | Order identity and fill execution identity are unique | Durable helper suppresses duplicates | Bind all automated records to tenant/run/fence/evaluation identities |
| `PaperPosition` / `PaperAccountSnapshot` / `PaperLedgerEntry` | Paper service direct ORM | Updated with fill, but ledger has no unique execution identity | Recomputed only by reporting code | Add run/fence/version and unique economic-effect identities; reconcile before recovery |
| `DailyRiskState` / `RiskDecision` | Risk service direct ORM | Scope/day state and per-intent decision | Checked on new intent only | Persist deterministic run risk counters and reconcile to fills/ledger |
| `SimulationCheckpoint` | Fenced helper | Unique run/sequence; opaque JSON; no integrity hash | Version fields checked only | Define canonical schema/hash and validate market, evaluation, economic, risk, and ledger invariants |
| Outbox claim/consume | Database claim with `SKIP LOCKED`; signed tenant job | Event/state transaction and consumer effect/ack transaction | Expired claims redeliver | Add evaluation events and crash-boundary evidence; publication remains at-least-once |
| Process startup/shutdown | FastAPI lifespan starts periodic recovery | Database is authoritative | Same-process startup recovery only tested | Add a subprocess drill against persistent PostgreSQL |
| Manual `/scheduler/execute-trade` | Authenticated HTTP user | Existing paper service | Existing paper reconciliation behavior | Keep outside automated run workflow and regression-test unchanged |

## Existing automated mutation paths without a complete fence

- `record_strategy_signal` can create and commit an automated signal without a run
  or fence if called by new code.
- `execute_paper_order` can create orders, fills, positions, snapshots, ledger
  entries, and risk decisions without a run or fence. It remains authorized only
  for explicit manual paper orders.
- `_apply_fill_to_position_and_ledger` has no durable execution identity and must
  not be called by the automated worker.
- `scheduler.fetch_price_data` obtains Topstep data with an application credential
  and has neither stable input identity nor hosted-beta provider approval.

Architectural tests SHALL keep those legacy functions out of the worker and
status/SSE call graphs. Automated simulation effects SHALL be created only by the
fenced durable evaluation service.

## Authoritative automated transaction boundary

One database transaction SHALL lock the run and active lease, validate kill,
fence, configuration, strategy, schedule, reconciliation lock, and input
freshness; persist the market classification and deterministic evaluation;
persist the risk decision; optionally persist distinct order intent and modeled
fill; apply position, snapshot, ledger, P&L, and risk counters; append outbox
events; and commit the next integrity-protected checkpoint. A rollback leaves no
partial economic effect. Redelivery is safe through stable unique identities.

The HTTP ingestion boundary may only persist a market-input record. It MUST NOT
evaluate a strategy or produce an execution effect.
