## ADDED Requirements

### Requirement: Execution uses a fail-closed local lifecycle
The executor SHALL persist the states `disabled`, `observe_only`, `practice_armed`, `practice_qualified`, `combine_pending`, `combine_armed`, `running`, and `halted`, and SHALL permit provider mutations only in the account-appropriate armed or running state. Restart and invalidation rules SHALL never infer a more permissive state.

#### Scenario: Executor restarts while Combine was armed
- **WHEN** the local executor restarts after a Combine arming ceremony
- **THEN** short-lived arming is cleared and a new local confirmation is required before any mutation

#### Scenario: Integrity or state validation fails
- **WHEN** lifecycle, database, policy, credential, clock, account, or reconciliation validation fails
- **THEN** the executor enters or remains in a non-ordering state

### Requirement: Practice qualification precedes Combine arming
The selected installation, credential generation, strategy/configuration version, and risk-policy version SHALL complete owner-defined Practice-account qualification before the executor can enter `combine_pending`. Qualification SHALL include normal order lifecycle, risk rejection, cancellation, restart recovery, ambiguity handling, reconciliation, and kill evidence.

#### Scenario: Practice evidence is incomplete
- **WHEN** any required Practice scenario lacks current successful evidence
- **THEN** Combine arming is denied with a safe missing-evidence classification

#### Scenario: Qualified configuration changes
- **WHEN** credentials, executable version, strategy, configuration, risk policy, or required provider behavior changes
- **THEN** affected Practice qualification is invalidated and must be repeated

### Requirement: Exact Combine account requires explicit local attestation
Combine arming SHALL require rediscovery of one visible and tradable account, an exact account-ID allowlist, explicit attestation that the account is a Trading Combine rather than Practice, Express Funded, or Live Funded, and typed confirmation of a redacted account suffix. Account names MUST NOT establish account type.

#### Scenario: User selects an account by name only
- **WHEN** a user attempts to authorize an account based on its display name or a name pattern
- **THEN** authorization is denied until exact-ID selection, attestation, and typed confirmation succeed

### Requirement: Consent is current and bound
The executor SHALL require current versioned consent bound to the installation, user, credential generation, exact account, strategy/configuration versions, and policy version. The consent SHALL explain that the Combine is simulated but orders can affect evaluation status, rule compliance, and subscription value.

#### Scenario: Policy changes after consent
- **WHEN** a new risk-policy version becomes active
- **THEN** prior consent cannot authorize Practice or Combine mutations

### Requirement: Local risk policy is complete and cannot be remotely relaxed
The active policy SHALL contain an exact account and nonempty instrument allowlists, allowed strategy/configuration versions, quantity fixed to one, position/order/session/day limits, daily and consecutive loss limits, allowed schedule, data-freshness and clock-skew limits, provider-error cooldowns, telemetry-loss behavior, and kill behavior. No hosted input or browser request may create, alter, or relax this policy.

#### Scenario: Quantity exceeds one
- **WHEN** a strategy or local UI proposes quantity greater than one
- **THEN** the risk decision denies the intent before a submission attempt exists

#### Scenario: Required policy value is absent
- **WHEN** any required policy field or allowlist is missing, empty, expired, or malformed
- **THEN** mutation-capable states remain unavailable

### Requirement: Kills are local and layered
The executor SHALL provide installation, account, strategy-run, reconciliation, stale-data, loss, authentication, and manual local kills. An active kill MUST block new provider mutations except a separately authorized cancellation or risk-reducing close allowed by local policy. Hosted alerts MUST NOT act as remote kill commands.

#### Scenario: Hosted dashboard requests a stop
- **WHEN** a hosted user action or telemetry response attempts to stop, cancel, close, or alter the local executor
- **THEN** the local executor ignores or rejects it as a prohibited remote command

### Requirement: Combine arming is short-lived and locally confirmed
After Practice qualification, Combine execution SHALL require a recent read-only preflight, clean reconciliation, no unexplained open order or position, current consent and policy, and an immediate local confirmation. Arming SHALL expire after an owner-configured short interval and on restart.

#### Scenario: Arming expires before submission
- **WHEN** the configured arming interval elapses before an order attempt begins
- **THEN** the proposed order is denied and a new local arming ceremony is required

### Requirement: First Combine order is individually authorized
The first Trading Combine order for an installation, credential generation, exact account, strategy/configuration version, or policy version SHALL require immediate local human authorization for one quantity-one intent and SHALL be reconciled before automated Combine sessions can be enabled.

#### Scenario: Automated session starts before acceptance review
- **WHEN** software attempts an automated Combine session without reviewed first-order evidence
- **THEN** execution is denied even if Practice qualification and general arming are current

### Requirement: Funded and live stages remain unavailable
The executor MUST reject Express Funded, Live Funded, live brokerage, live contract/history selection, trade copying, multi-account execution, and account switching. A new reviewed change SHALL be required to alter any of these prohibitions.

#### Scenario: User attests to a funded account
- **WHEN** the selected account is identified or attested as Express Funded or Live Funded
- **THEN** the executor refuses to arm or send any provider mutation

