## ADDED Requirements

### Requirement: Locked clean installation
Backend production and development environments SHALL install from committed exact lockfiles, and frontend verification SHALL begin with `npm ci`.

#### Scenario: Clean backend environment
- **WHEN** an empty virtual environment installs the production then test lock
- **THEN** imports, `pip check`, migrations, tests, and demo smoke SHALL succeed without undeclared packages

#### Scenario: Clean frontend environment
- **WHEN** dependencies are removed and installed with `npm ci`
- **THEN** frontend tests, build, and production audit SHALL pass

### Requirement: Dependency audit disposition
CI SHALL fail for unaccepted production vulnerabilities and SHALL retain explicit evidence for any accepted advisory.

#### Scenario: New critical advisory
- **WHEN** a production dependency audit reports an unaccepted critical advisory
- **THEN** the release gate SHALL fail
