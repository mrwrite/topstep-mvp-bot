# Durable execution migration inventory

Inventory date: 2026-07-29.

| Entry point | Current owner | Tenant source | Persisted state used | Recovery behavior | Migration required |
| --- | --- | --- | --- | --- | --- |
| `POST /scheduler/bot-sessions` | `BOT_STATES` / `BOT_SESSIONS` | authenticated user | strategy config only | none | durable run plus idempotent start command |
| `POST /scheduler/stop-bot` | `BOT_STATES[user].stop` | authenticated user | none | restart clears stop | tenant-owned durable stop command |
| `GET /scheduler/run-bot` | SSE coroutine / dictionaries | session ID only | signals and orders only | none | authenticated status stream; fenced worker owns execution |
| `POST /risk/kill-switches` | risk service/current process | authenticated user | kill-switch row | kill persists but run state does not | durably kill matching runs and supersede execution commands |
| Dashboard controls | browser calls above | cookie session | cached UI state | refetch only | consume durable command/run responses |
| Demo session | scheduler creation route | authenticated demo user | paper records | none | durable start while remaining simulation-only |
| Strategy/market loop | SSE coroutine | dictionary tenant | signals | evaluation position lost | fenced worker and durable checkpoint |
| Risk/order/fill/ledger | paper service from SSE | dictionary-derived intent | durable domain rows | order-key dedupe only | active tenant/run/fence required |
| Status | SSE text/dictionaries | session ID | none | freshness unknown | tenant-scoped persisted status |
| Startup | no recovery hook | none | none | none | scan expired eligible runs/outbox using verified tenant jobs |

`BOT_STATES`, `BOT_SESSIONS`, `get_bot_state`, direct stop mutation, and the legacy `/run-bot` loop are beta-reachable process-local authority. They MUST be removed or reduced to compatibility aliases which resolve durable state and own no execution state.

The scheduler also directly queries users and strategy configuration and calls trading-context, risk, strategy, paper execution, ledger, analytics, and provider services. Migrated HTTP work SHALL derive `TenantContext` from the authenticated session; background work SHALL validate its signed job envelope. Cross-tenant identifiers SHALL be indistinguishable from missing identifiers.
