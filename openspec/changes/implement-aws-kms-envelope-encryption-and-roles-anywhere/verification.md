# Verification status

> **Superseded historical evidence only.** No command below is an active release or operational instruction. No real cloud drill occurred.

## Completed locally

```text
python -m pytest -q tests/test_aws_kms_envelope.py tests/test_simulation_beta_managed_secrets.py
10 passed
openspec validate implement-aws-kms-envelope-encryption-and-roles-anywhere --strict
valid
```

The tests cover context binding, tampering, provider outage, key-version
rotation, restart using the same ciphertext, disablement failure, legacy
dual-read/single-write conversion, and production Roles Anywhere configuration
requirements. The AWS provider test double is not production evidence.

## Required external evidence (open)

- Real AWS KMS customer-managed key encrypt/decrypt with IAM Roles Anywhere
  short-lived credentials.
- Certificate expiry, revocation, replacement, and credential-helper restart.
- Pi-hosted TPM 2.0 private-key use and filesystem-key rejection.
- KMS key disablement, unavailable region, application restart, backup restore,
  and rollback drills.
- Proof that the legacy Fernet key is rejected after migration and owner
  approval of the resulting rollback/retention policy.

No task in this list is complete based solely on the local provider test double,
LocalStack, or an unverified IaC template.
