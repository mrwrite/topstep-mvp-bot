## ADDED Requirements

### Requirement: Secure account lifecycle
The system SHALL provide registration, email verification, sign-in, sign-out, password reset, profile management, and session listing/revocation without revealing whether an email address is registered. Passwords MUST meet a versioned policy, be stored with an approved adaptive hash, and successful password reset MUST revoke existing sessions.

#### Scenario: Recovery revokes sessions
- **WHEN** a user completes password reset with a valid single-use token
- **THEN** the password hash is replaced, all prior sessions are revoked, the token cannot be reused, and the action is audited without the password or token

### Requirement: Tenant isolation and operator authorization
Every user-owned record and command SHALL be scoped by an authenticated tenant context. Operator access MUST require an authorized role, declared support or incident purpose, case reference, and an audit event.

#### Scenario: Cross-tenant identifier is supplied
- **WHEN** an authenticated user requests another tenant's session, connection, configuration, order, fill, export, or support record by identifier
- **THEN** the system returns a non-disclosing denial and neither reads nor mutates that record

### Requirement: Account export and deletion
The system SHALL provide authenticated machine-readable export and deletion workflows. Deletion MUST stop automation, revoke broker grants, apply approved retention or legal holds, remove or pseudonymize eligible data, and produce a receipt.

#### Scenario: User deletes account
- **WHEN** a verified user confirms account deletion after reauthentication
- **THEN** active runs stop, broker grants are revoked, eligible tenant data is deleted or pseudonymized, retained categories and expiry dates are disclosed, and login is disabled
