from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from local_executor.journal import LOCAL_SCHEMA_REVISION
from local_executor.release import canonical_manifest_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a detached signed manifest for a code-signed local executor."
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--valid-days", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.valid_days <= 90:
        raise SystemExit("--valid-days must be between 1 and 90")
    artifact = args.artifact.resolve(strict=True)
    private_key_path = args.private_key.resolve(strict=True)
    key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=None
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("release private key must be Ed25519")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    manifest = {
        "artifact_sha256": sha256(artifact.read_bytes()).hexdigest(),
        "expires_at": (now + timedelta(days=args.valid_days)).isoformat(),
        "issued_at": now.isoformat(),
        "minimum_policy_version": 1,
        "revoked": False,
        "schema_max": LOCAL_SCHEMA_REVISION,
        "schema_min": LOCAL_SCHEMA_REVISION,
        "version": args.version,
    }
    signature = key.sign(canonical_manifest_payload({**manifest, "signature": ""}))
    manifest["signature"] = base64.b64encode(signature).decode("ascii")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "classification": "release_manifest_signed",
        "manifest": str(args.output),
        "artifact_sha256": manifest["artifact_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
