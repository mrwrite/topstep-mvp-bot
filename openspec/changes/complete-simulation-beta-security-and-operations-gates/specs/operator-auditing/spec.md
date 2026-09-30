## ADDED Requirements

### Requirement: Complete operator action evidence
Every operator action SHALL append correlated authorization, start, and terminal outcome events containing actor, tenant, purpose, case, target, action, timestamps, safe resource references, and confirmation state.

#### Scenario: Authorized success
- **WHEN** an authorized operator action succeeds
- **THEN** correlated authorized, started, and succeeded events SHALL exist

#### Scenario: Authorized partial external result
- **WHEN** a local action succeeds but external revocation is unconfirmed
- **THEN** the terminal outcome SHALL be partial and SHALL identify confirmation as unconfirmed

#### Scenario: Denied investigation
- **WHEN** an operator lacks purpose, case, or matching target
- **THEN** a denied event SHALL be appended and no target data SHALL be returned

### Requirement: Audit secrecy and immutability
Ordinary application paths MUST NOT update or delete operator audit events and all summaries SHALL pass centralized redaction.

#### Scenario: Secret-bearing failure
- **WHEN** an operator action fails with a token or credential in an exception
- **THEN** the audit event SHALL contain only a safe failure classification and redacted message

### Requirement: Exceptional target-bound operator persistence
Operator tenant access SHALL use an expiring target tenant context after
authorization and SHALL use the ordinary tenant repository for target data.
Global operator reads SHALL be restricted to an explicit metadata-model
allowlist and MUST NOT provide unrestricted tenant queries.

#### Scenario: Operator target mismatch
- **WHEN** the path resource tenant differs from the authorized operator target
- **THEN** access SHALL be denied, the attempt SHALL be audited, and target data SHALL NOT be returned

#### Scenario: Expired operator context
- **WHEN** an operator context expires before persistence access
- **THEN** the repository SHALL reject it and SHALL NOT silently extend or reuse the context

### Requirement: Topstep account approval is purpose-bound
An operator approval or revocation SHALL require an unexpired target-bound operator context and SHALL persist actor, purpose, case, correlation, exact tenant/integration/generation/account/attestation/cohort, expiry, and terminal outcome without secrets.

#### Scenario: Ordinary user attempts approval
- **WHEN** an end-user context invokes the operator approval port
- **THEN** the request SHALL fail without revealing cross-tenant resource existence or creating approval evidence
