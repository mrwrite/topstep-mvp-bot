## Why

The repository has a credible paper-only demo and a growing set of user, risk, audit, and beta controls, but it is not ready for external users or live money. A reviewed, evidence-based plan is required now because multi-user isolation, dependency security, broker authorization, order-state correctness, operational recovery, and truthful platform support must be release gates rather than assumptions.

## What Changes

- Preserve the working `rsi-threshold-v1`, paper execution, demo seed/reset, risk settings, kill switches, reconciliation locks, launch gates, and existing tests while defining the gaps that must be closed.
- Establish provider-neutral broker contracts with capability discovery, paper/live environment identity, least-privilege authorization, account and instrument discovery, market data, order lifecycle, reconciliation, and health behavior.
- Define secure multi-tenant identity, session, credential, data-export, deletion, and operator-access requirements.
- Define versioned bot, instrument, session, strategy, and risk configuration with server-side validation before execution.
- Define deterministic simulation and broker-paper behavior that reports fees, spread, slippage, fill assumptions, and limitations without implying future returns.
- Require an explicit, server-enforced live activation ceremony and keep live trading unavailable until every security, execution, reconciliation, risk, legal, and operational gate passes.
- Establish durable audit traceability from market input through signal, decision, order, event, fill, position, balance, and P&L.
- Establish staged beta operations, monitoring, notifications, incident response, data retention, rollback, support ownership, and objective go/no-go criteria.
- Correct product claims so only officially documented, technically implemented, contractually permitted capabilities are presented as supported.
- Use simulation-only internal and invite-only beta stages first. Target Tradovate demo and Alpaca paper as the first broker-paper candidates after adapter implementation and provider approval; treat IBKR as a planned integration; keep TopstepX hosted automation out of the external beta while its personal-device and Live Funded Account restrictions apply.
- Do not implement the broad application changes in this proposal; implementation begins only after owner review and approval.

## Capabilities

### New Capabilities

- `user-identity-account-management`: Registration, verification, authentication, sessions, recovery, profile, export, deletion, and tenant isolation.
- `broker-connection-management`: Secure provider authorization, account selection, credential lifecycle, revocation, and disconnect behavior.
- `broker-adapter-capabilities`: Canonical adapter operations, provider-specific capability discovery, normalization, throttling, and fail-closed preflight.
- `bot-strategy-configuration`: Versioned account, instrument, schedule, strategy, and parameter configuration with validation and activation state.
- `simulation-paper-trading`: Deterministic local simulation and broker paper-account execution with explicit modeling assumptions and environment separation.
- `live-trading-activation`: Explicit consent ceremony, readiness evidence, account verification, server enforcement, and revocation for any future live mode.
- `risk-management`: Server-side pre-trade, intraday, exposure, loss, trade-count, stale-data, connectivity, and emergency-stop controls.
- `order-execution-reconciliation`: Idempotent order state machines, submit/cancel/replace, events, partial fills, positions, balances, P&L, and deterministic reconciliation.
- `audit-history-explainability`: Immutable user-scoped traceability for inputs, signals, decisions, orders, fills, interventions, and operator access.
- `monitoring-user-notifications`: Health, degraded states, alerts, incident signals, user notifications, and redacted operational diagnostics.
- `data-security-privacy`: Encryption, key rotation, redaction, least privilege, retention, export, deletion, backups, and privacy-safe analytics.
- `beta-operations-support`: Invite stages, entry/exit gates, user caps, support ownership, incident thresholds, rollback, disclosures, and known-risk acceptance.

### Modified Capabilities

None. There are no archived base specifications under `openspec/specs/`; the existing change specifications remain historical inputs.

## Impact

- Backend APIs, auth/session services, broker providers, scheduler/worker execution, trading context, risk, reconciliation, strategy, analytics, observability, and health behavior.
- Database schemas and migrations for tenant ownership, authorization grants, credentials, configurations, execution/audit events, operations, retention, and deletion.
- Frontend onboarding, integration setup, environment identity, readiness, intervention, activity explanation, accessibility, and account controls.
- Dependency management, CI quality gates, deployment configuration, secrets management, backups, restore tests, monitoring, incident response, and rollback.
- Provider agreements and commercial approvals for Tradovate/NinjaTrader, Alpaca, IBKR, TopstepX/ProjectX, market-data licensing, and any later integration.
- Product, legal, privacy, risk, support, pricing, and performance-claim disclosures requiring owner and qualified counsel review.
