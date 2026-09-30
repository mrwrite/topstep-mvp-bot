# Tasks

> **Status: Superseded.** Completed boxes record historical work only. Tasks 2, 5, 6, and 7 were not completed and MUST remain unchecked. The TPM replacement change owns all current work.

- [x] 1. Add AWS KMS provider and context-bound envelope integration with sanitized failures and fail-closed configuration.
- [ ] 2. Add dual-read/single-write legacy Fernet migration with lazy re-encryption and rollback tests.
- [x] 3. Add AWS KMS/Roles Anywhere configuration, IAM/KMS IaC, and deployment runbook without committed credentials.
- [x] 4. Add deterministic provider tests for encryption, tampering, context, rotation, outage, disablement, and restart semantics.
- [ ] 5. Run a real AWS KMS non-production drill using Roles Anywhere short-lived credentials and record evidence.
- [ ] 6. Run Pi-hosted recovery with TPM-backed key, certificate expiry/rotation, restore, and region-failure drills.
- [ ] 7. Verify legacy key rejection after migration and obtain owner approval; keep the parent managed-KMS task and beta gate open until then.
