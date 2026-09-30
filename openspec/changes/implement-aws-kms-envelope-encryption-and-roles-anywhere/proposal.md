# Implement AWS KMS envelope encryption and IAM Roles Anywhere

> **Status: Superseded on 2026-09-23.** The owner prohibited AWS before production integration. Provider-neutral envelope work was retained, every AWS-specific runtime/dependency/configuration/template/test/documentation artifact was removed, and the four incomplete tasks remain incomplete. `replace-aws-kms-with-tpm-backed-local-key-management` is authoritative. This file is inactive historical evidence only.

## Motivation

The Raspberry Pi deployment currently has a provider-neutral envelope service
but production cannot safely select a real managed key authority. This slice
adds an AWS KMS implementation designed for workloads outside AWS, with
short-lived credentials obtained through IAM Roles Anywhere and an optional
TPM-backed private key. It preserves fail-closed behavior and does not claim
production readiness without real AWS and Pi-hosted evidence.

## Scope

- AWS KMS customer-managed symmetric-key provider.
- KMS encryption-context binding for tenant, purpose, record, environment, and
  schema version.
- Provider-neutral configuration and startup validation.
- Legacy Fernet dual-read with single-write envelope migration.
- AWS/TPM/IAM Roles Anywhere deployment templates and rotation/outage drills.
- Tests using deterministic provider doubles plus explicit real-AWS evidence
  tasks that cannot be satisfied by LocalStack alone.

## Out of scope

Broker adapters, live trading, paper-broker execution, automatic AWS account
provisioning, certificate private-key generation, and claims of compliance or
beta readiness.

## Release posture

The managed-KMS parent task remains open until AWS KMS, Roles Anywhere,
certificate rotation, TPM protection, restart/restore, disablement, and region
failure evidence are attached to a controlled non-production deployment.
