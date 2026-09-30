# Design

> **Superseded historical design.** Do not use this document for deployment or operations. The owner rejected AWS; the TPM replacement change is authoritative.

## Provider boundary

`KeyManagementProvider` remains the application boundary. The AWS implementation
uses KMS `Encrypt` and `Decrypt` to wrap a unique per-record AES-GCM data key.
The KMS request includes non-secret authenticated context; the application never
sends plaintext integration credentials to KMS as the data payload. The AWS SDK
credential chain is expected to be fed by the IAM Roles Anywhere credential
helper, not permanent access keys.

## Context and rotation

KMS context contains only `tenant_id`, `purpose`, `record_type`, `record_id`,
`environment`, `schema_version`, and `key_version`. The envelope stores provider
and key-version metadata. Decryption accepts retained previous versions and
returns a rotation-needed signal; writes always use the active version. Legacy
Fernet ciphertext is read only when explicitly enabled and is eligible for
lazy re-encryption after a successful read.

## Raspberry Pi trust bootstrap

IAM Roles Anywhere uses an X.509 workload certificate and private key. The
certificate should be short lived and the private key should be TPM 2.0-backed.
Without TPM protection, copied private-key material can impersonate the Pi until
revocation or expiry; this is a documented production blocker. No certificate,
private key, AWS credential, or KMS key material is committed.

## Failure behavior

Missing configuration, invalid provider selection, unavailable KMS, expired
credentials, disabled keys, retired versions, malformed ciphertext, or context
mismatch fail closed with sanitized errors. No plaintext fallback is permitted.

## Infrastructure as code

The template under `infra/aws-kms-roles-anywhere/` creates a customer-managed
symmetric KMS key and narrowly scoped IAM policy placeholders. Trust-anchor,
profile, certificate, and TPM enrollment remain deployment-owned operations and
must be completed and evidenced outside this repository.
