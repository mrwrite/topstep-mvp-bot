## ADDED Requirements

### Requirement: Hardware-backed local authority
Production credential protection MUST use physical TPM-backed local key management and MUST NOT depend on AWS, another cloud KMS, or a hosted secrets-management service.

#### Scenario: Cloud dependency configured
- **WHEN** an active production dependency, configuration, template, or instruction selects a cloud key service
- **THEN** architectural validation SHALL fail
