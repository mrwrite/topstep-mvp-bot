# ADR 0001: Physical TPM 2.0 is the production key authority

Status: accepted architecture; physical evidence remains a release blocker

The owner rejected all cloud infrastructure and hosted key-management services. Production targets a self-hosted Raspberry Pi and MUST use a physical TPM 2.0 with a non-exportable, versioned wrapping key. Local software wrapping remains restricted to development and test.

The approved implementation uses TPM2-TSS through `tpm2-tools`, `/dev/tpmrm0`, a persistent RSA-2048 key, OAEP with SHA-256, public-key fingerprint pinning, and a separate RSA-3072 offline recovery public key. The recovery private key is encrypted and stored offline, separated from database backups and never placed on the Pi.

PCR binding is deferred because the target boot chain and update behavior have not been characterized. This avoids a ceremonial policy that locks out normal firmware, kernel, initramfs, or bootloader updates. Measured-boot binding requires a separate signed-policy and recovery drill.

Rejected alternatives are PKCS#11 for the first slice (extra token-store/PIN lifecycle), a Python TPM binding without demonstrated target compatibility, file/environment master keys, software TPMs, and every remote or hosted key service.

Acceptance still requires physical-Pi provisioning, object-attribute/non-exportability evidence, reboot and upgrade drills, lockout/failure behavior, rotation, restored-backup recovery to a replacement TPM, legacy migration/cutover, and owner approval for custody and retirement.
