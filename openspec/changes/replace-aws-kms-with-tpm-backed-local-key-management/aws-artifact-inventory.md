# Supersession inventory

Owner decision date: 2026-09-23. AWS is prohibited and the prior child was superseded before production integration.

| Artifact | Classification | Disposition |
|---|---|---|
| `app/key_management.py` provider protocol, per-record DEKs, AES-GCM, context, sanitized failures | Provider-neutral and retained | Refactored to schema 2, lifecycle/health, integrity MAC, TPM and recovery support |
| `app/key_management.py` AWS provider/import/error adapter | Removed | No active provider or SDK import remains |
| `app/crypto.py` envelope integration and explicit legacy conversion | Provider-neutral and retained | Rewritten for explicit TPM selection and envelope-only cutover |
| `app/crypto.py` AWS environment/configuration | Removed | Replaced by TPM handle/public/fingerprint/device and recovery-public settings |
| `app/app_config.py` production provider enforcement | Provider-neutral and retained | Rewritten to require physical TPM and reject cloud/development providers |
| AWS SDK and transitive entries in Python locks | Removed | `boto3`, `botocore`, `jmespath`, and `s3transfer` removed |
| `tests/test_aws_kms_envelope.py` | Removed | Replaced by deterministic TPM/provider/envelope/recovery tests |
| `infra/aws-kms-roles-anywhere/*` | Removed | Replaced by least-privilege Raspberry Pi TPM container example |
| AWS/Roles Anywhere ADR and active operator guidance | Removed | Replaced by physical TPM ADR and operations runbook |
| Prior child proposal/design/spec/tasks/verification | Historical evidence retained only | Clearly marked superseded; four incomplete tasks left unchecked |
| Parent managed-secret/release/operations requirements | Rewritten for TPM | Hardware, recovery, migration, warning, install, backup, approval, and CI gates remain open |
| CI | Rewritten | Architectural scan prevents prohibited SDK/config/provider artifacts and direct TPM calls outside the boundary |

The inventory search covers SDK dependencies, lockfiles, imports, configuration, provider code, tests, infrastructure, IAM workload integration, credential-helper references, error handling, documentation, ADRs, OpenSpec artifacts, CI, and deployment examples. No active production document directs an operator to AWS.
