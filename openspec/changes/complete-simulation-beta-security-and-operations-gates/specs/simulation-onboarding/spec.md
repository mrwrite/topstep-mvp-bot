## ADDED Requirements

### Requirement: Simulation-only admission
The onboarding flow SHALL require an eligible invite, secure authentication, current required acceptance, available cohort capacity, and explicit acknowledgement that execution and performance are simulated.

#### Scenario: Cohort full
- **WHEN** the configured active simulation cohort cap is reached
- **THEN** further admission SHALL fail with a non-sensitive waitlist message

### Requirement: Honest configuration validation
Users SHALL configure only supported simulated instruments, `rsi-threshold-v1` parameters, schedules, and risk limits, with server-side validation and no unavailable broker credential controls.

#### Scenario: Unsupported instrument
- **WHEN** a user submits an unsupported simulated instrument
- **THEN** activation SHALL fail before a run is created
