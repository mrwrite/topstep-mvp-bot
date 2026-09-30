## ADDED Requirements

### Requirement: Classified warning baseline
Warnings SHALL be counted by category and source with owner, risk, remediation, and expiring allowance metadata.

#### Scenario: Unclassified warning
- **WHEN** tests emit a warning absent from the approved baseline
- **THEN** CI SHALL fail the warning-budget check

### Requirement: No broad warning suppression
Warning filters MUST be narrow and documented and MUST NOT globally ignore security, resource, runtime, or application deprecation warnings.

#### Scenario: Budget regression
- **WHEN** an approved warning category exceeds its count budget
- **THEN** CI SHALL fail and report the category/source delta
