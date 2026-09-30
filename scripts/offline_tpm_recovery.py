"""Offline recovery ceremony: rewrap envelope DEKs to a replacement TPM public key."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.key_management import (EncryptionContext, KeyManagementError, Tpm2KeyProvider,
                                rewrap_recovered_envelope)


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def recover_package(package: dict, private_key_pem: bytes, passphrase: bytes,
                    replacement: Tpm2KeyProvider) -> tuple[dict, dict]:
    private = serialization.load_pem_private_key(private_key_pem, password=passphrase)
    output = {"schema_version": 1, "records": []}
    failures = 0
    for record in package.get("records", []):
        data_key = None
        try:
            envelope = record["envelope"]
            encoded = envelope.removeprefix("envelope:v2:")
            payload = json.loads(_b64d(encoded))
            recovered = private.decrypt(_b64d(payload["recovery_wrapped_data_key"]), padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            data_key = bytearray(recovered)
            context = EncryptionContext(**record["context"])
            output["records"].append({
                "record_reference": record["record_reference"],
                "envelope": rewrap_recovered_envelope(envelope, context, data_key, replacement),
            })
        except (KeyManagementError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            failures += 1
        finally:
            if data_key is not None:
                for index in range(len(data_key)):
                    data_key[index] = 0
    report = {"total": len(package.get("records", [])), "rewrapped": len(output["records"]),
              "failed": failures, "replacement_key_id": replacement.key_id,
              "replacement_key_version": replacement.active_version}
    return output, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline replacement-TPM data-key rewrap")
    parser.add_argument("--package", required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--recovery-private-key", required=True)
    parser.add_argument("--replacement-public-key", required=True)
    parser.add_argument("--replacement-fingerprint", required=True)
    parser.add_argument("--replacement-key-id", required=True)
    parser.add_argument("--replacement-key-version", required=True)
    parser.add_argument("--replacement-handle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit-report", required=True)
    args = parser.parse_args()
    package_path = Path(args.package)
    package_bytes = package_path.read_bytes()
    if hashlib.sha256(package_bytes).hexdigest() != args.package_sha256.lower():
        raise SystemExit("Recovery package integrity verification failed.")
    public_pem = Path(args.replacement_public_key).read_bytes()
    replacement = Tpm2KeyProvider(
        key_id=args.replacement_key_id, active_version=args.replacement_key_version,
        handles={args.replacement_key_version: args.replacement_handle},
        public_keys_pem={args.replacement_key_version: public_pem},
        approved_fingerprints={args.replacement_key_version: args.replacement_fingerprint},
        command_runner=lambda _args, _input: b"", require_physical_device=False,
    )
    passphrase = getpass.getpass("Recovery private-key passphrase: ").encode()
    try:
        output, report = recover_package(json.loads(package_bytes),
                                         Path(args.recovery_private_key).read_bytes(), passphrase, replacement)
    finally:
        passphrase = b""
    Path(args.output).write_text(json.dumps(output, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    report["input_package_sha256"] = args.package_sha256.lower()
    report["output_sha256"] = hashlib.sha256(Path(args.output).read_bytes()).hexdigest()
    Path(args.audit_report).write_text(json.dumps(report, sort_keys=True, indent=2), encoding="utf-8")
    return 0 if report["failed"] == 0 and report["total"] == report["rewrapped"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
