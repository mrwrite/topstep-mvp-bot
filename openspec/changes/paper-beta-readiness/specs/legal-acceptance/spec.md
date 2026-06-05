## ADDED Requirements

### Requirement: Versioned legal documents
The system SHALL model terms of service, privacy policy, and paper-trading risk disclosure as versioned documents.

#### Scenario: Current documents are requested
- **WHEN** a user opens the legal acceptance flow
- **THEN** the system returns the current required versions and acceptance state for that user

### Requirement: Legal acceptance records
The system SHALL persist user-scoped acceptance records for each required legal document version.

#### Scenario: User accepts required documents
- **WHEN** a user confirms terms, privacy, and paper-trading risk disclosure
- **THEN** the system records document type, version, user id, timestamp, IP hash, user-agent summary, and acceptance metadata

### Requirement: Paper-trading disclosure gate
The system SHALL require current paper-trading risk disclosure acceptance before paper-beta trading workflows are available.

#### Scenario: Disclosure missing
- **WHEN** a user without current paper-risk disclosure acceptance tries to start a paper session
- **THEN** the system blocks the workflow with `paper_disclosure_required`

### Requirement: Re-acceptance workflow
The system SHALL require re-acceptance when a required legal document version changes.

#### Scenario: Terms version changes
- **WHEN** a new terms version becomes required
- **THEN** previously accepted users must re-accept before accessing beta product surfaces

### Requirement: Acceptance audit isolation
Legal acceptance records SHALL be user-scoped and unavailable across users.

#### Scenario: User requests acceptance history
- **WHEN** a user requests legal acceptance history
- **THEN** only that user's records are returned
