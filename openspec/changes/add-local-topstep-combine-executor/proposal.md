## Why

The current hosted-Combine design assigns Topstep order transmission to a Railway worker, but Topstep's current API policy requires trading activity and automated order access to originate from the trader's personal device and prohibits VPS or remote-server order routing. The product needs a local execution boundary so one invited user can safely test an automated strategy first in Practice and then in a Trading Combine without enabling real-money trading or using Railway to place, modify, or cancel orders.

## What Changes

- Add a personal-device executor that owns Topstep authentication, market input, strategy decisions, risk checks, order submission, cancellation, reconciliation, and emergency stopping.
- Keep Topstep credentials and provider sessions on the user's device; they are never uploaded to Railway, Vercel, browser storage, hosted logs, or hosted analytics.
- Restrict Railway and Vercel to read-only administration, health, and sanitized telemetry. Hosted services cannot create, relay, queue, approve, or trigger an order-capable instruction.
- Require a current local policy, explicit user consent, exact-account selection, local kill controls, and successful Practice-account acceptance before Trading Combine execution can be enabled.
- Add durable local intent, attempt, acknowledgement, order, fill, position, and reconciliation state so ambiguous provider outcomes are reconciled before retry.
- Add signed/versioned local software and configuration checks, startup preflight, update/rollback procedures, and redacted evidence for controlled Combine acceptance.
- **BREAKING**: Supersede the hosted-worker provider-execution target. Railway workers remain mutation-disabled and cannot be used as a fallback executor.
- Preserve the prohibition on Express Funded, Live Funded, live-brokerage, multi-user, and unattended remote-server execution.

## Capabilities

### New Capabilities

- `personal-device-topstep-execution`: Local-only Topstep authentication, simulated-account discovery, strategy execution, provider mutations, and reconciliation from the trader's personal device.
- `local-combine-safety`: Server-independent local risk policy, consent, exact-account authorization, Practice-first qualification, kill controls, fail-closed recovery, and controlled Trading Combine activation.
- `hosted-read-only-telemetry`: Railway/Vercel boundaries for sanitized health, positions, fills, P&L, and audit telemetry without credentials, provider sessions, order routing, or execution triggers.
- `local-executor-operations`: Installation, OS-backed secret custody, version/configuration integrity, startup preflight, monitoring, upgrades, rollback, incident response, and acceptance evidence for the personal-device executor.

### Modified Capabilities

No canonical capabilities currently exist under `openspec/specs/`. This change will supersede the conflicting Railway-worker execution requirements in the active hosted-Combine change before implementation is released.

## Impact

Affected areas include the Topstep adapter, provider capability declarations, local runtime packaging and configuration, secret storage, strategy and risk services, durable order/reconciliation models, telemetry APIs, Railway worker permissions, Vercel controls, tests, deployment documentation, and release-governance evidence. The hosted database may retain sanitized observational records, but local execution state remains authoritative for provider actions. No real Topstep order will be sent by automated tests or without a separate immediate acceptance authorization.
