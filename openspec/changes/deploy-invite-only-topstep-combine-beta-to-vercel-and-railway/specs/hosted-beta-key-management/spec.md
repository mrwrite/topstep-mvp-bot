## ADDED Requirements

### Requirement: Explicit hosted-beta envelope provider
The system SHALL expose `railway-secret-envelope-v1` only in the explicitly configured hosted Topstep Combine beta mode and SHALL reject it in other production profiles.

#### Scenario: Invalid deployment profile
- **WHEN** the Railway provider is selected outside the hosted Combine beta profile
- **THEN** startup fails before credential writes or worker execution are accepted

### Requirement: Versioned authenticated key wrapping
The provider SHALL load independently generated 256-bit key-encryption keys from private Railway service variables, use the active version only for writes, permit explicitly approved prior versions only for reads and rotation, and authenticate tenant, integration, credential record, environment, schema, and key version when wrapping each unique record data key.

#### Scenario: Context or version substitution
- **WHEN** wrapped data-key context or its declared key version differs from the stored authenticated values
- **THEN** unwrap fails closed without returning plaintext or secret-bearing diagnostics

### Requirement: Hosted root-key isolation and rotation
Hosted root keys MUST NOT be stored in PostgreSQL, Redis, Vercel, images, source, logs, API responses, or browser state, and rotation SHALL support idempotent rewrapping without record-plaintext re-encryption.

#### Scenario: Approved prior version is missing
- **WHEN** an envelope requires a prior key version that is not explicitly configured
- **THEN** the record is unavailable and the provider reports a safe typed failure rather than falling back

### Requirement: Hosted trust limitation
Operational documentation SHALL state that Railway project administrators and an authorized compromised runtime can access service variables and that this risk is accepted only for the one-user Trading Combine beta.

#### Scenario: Security posture review
- **WHEN** an operator reviews hosted-beta readiness
- **THEN** the provider is not described as TPM-equivalent or approved for funded or live-brokerage stages
