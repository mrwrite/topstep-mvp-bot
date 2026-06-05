## ADDED Requirements

### Requirement: Email verification before beta access
The system SHALL require a verified email address before a user can access invite-only paper-beta product surfaces.

#### Scenario: User registers with invite
- **WHEN** a new user completes registration with a valid invite code
- **THEN** the system creates the account in an unverified-email state and sends a verification link or code

#### Scenario: Unverified user opens dashboard
- **WHEN** an authenticated user without verified email opens a beta dashboard or paper-trading route
- **THEN** the system blocks access and returns a stable `email_verification_required` blocker

### Requirement: Password reset
The system SHALL provide a secure password reset workflow using expiring, single-use reset tokens.

#### Scenario: Reset token is consumed
- **WHEN** a user submits a valid reset token with a compliant new password
- **THEN** the password is updated, the reset token is consumed, and existing sessions are revoked

#### Scenario: Reset token is invalid
- **WHEN** a reset token is expired, already consumed, or unknown
- **THEN** the system rejects the reset without revealing whether the email exists

### Requirement: Account recovery support
The system SHALL provide an account recovery request workflow for beta support review.

#### Scenario: Recovery request submitted
- **WHEN** a user submits an account recovery request
- **THEN** the system records the request, redacts sensitive content, and returns a support reference id

### Requirement: Profile management
The system SHALL allow users to view and update beta-safe profile fields.

#### Scenario: User updates profile
- **WHEN** a user updates display name, timezone, preferred contact email, or optional experience level
- **THEN** the system validates the fields, persists the changes, and keeps the profile scoped to that user

### Requirement: Session management
The system SHALL persist user sessions and allow users to list and revoke active sessions.

#### Scenario: User revokes a session
- **WHEN** a user revokes an active session
- **THEN** the session can no longer authenticate requests and the revocation is audited

#### Scenario: Cross-user session access
- **WHEN** a user requests another user's session record
- **THEN** the system rejects the request without exposing session details
