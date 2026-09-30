## ADDED Requirements

### Requirement: End-to-end decision trace
The system SHALL provide an append-only, user-scoped trace from source market data and clock through strategy inputs, signal, guardrails, risk decision, order intent, broker events, fills, positions, balances, and P&L.

#### Scenario: User inspects a fill
- **WHEN** a user opens a fill record
- **THEN** the system links it to the originating configuration, market snapshot, strategy rationale, risk decision, order transitions, costs, and provider identifiers

### Requirement: Tamper evidence and redaction
Critical audit events SHALL include actor, tenant, environment, correlation/causation IDs, build/config versions, trusted timestamp, and sanitized metadata. Secrets and unnecessary provider payload fields MUST be absent or encrypted, and event integrity MUST be verifiable.

#### Scenario: Support investigates incident
- **WHEN** an authorized operator opens an incident trace
- **THEN** only allowlisted redacted data is shown and the operator access, purpose, case ID, and viewed resources are audited

### Requirement: User-understandable explanations
Decision explanations SHALL use stable reason codes and plain language and MUST distinguish no signal, data-quality suppression, risk rejection, provider rejection, pending submission, and confirmed fill.

#### Scenario: Submitted order has no fill
- **WHEN** an order is accepted by the provider but has no fill event
- **THEN** the UI displays it as working or pending and does not count it as a trade fill or realized P&L
