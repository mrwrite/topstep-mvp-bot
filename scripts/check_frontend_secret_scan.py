#!/usr/bin/env python3
"""Check built frontend files for configured private values without printing them."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
PRIVATE_NAME_MARKERS = ("SECRET", "TOKEN", "API_KEY", "PASSWORD", "ENVELOPE", "FINGERPRINT", "DATABASE", "REDIS")


def scan_frontend(env: dict[str, str] | None = None, dist: Path = DIST) -> tuple[bool, str]:
    env = env or dict(os.environ)
    if not dist.is_dir():
        return False, "frontend/dist is missing; run a production build first"
    files = [path for path in dist.rglob("*") if path.is_file()]
    if not files:
        return False, "frontend/dist is empty"
    blobs = []
    try:
        blobs = [path.read_bytes() for path in files]
    except OSError:
        return False, "frontend bundle could not be inspected"
    for name, value in env.items():
        if name == "VITE_API_URL" or not any(marker in name.upper() for marker in PRIVATE_NAME_MARKERS):
            continue
        if len(value) >= 8 and any(value.encode("utf-8") in blob for blob in blobs):
            return False, "a configured private value was found in the frontend bundle"
    public_api = env.get("VITE_API_URL", "")
    if public_api and not any(public_api.encode("utf-8") in blob for blob in blobs):
        return False, "configured public API URL was not found in the frontend bundle"
    return True, "configured private values absent; public API value found when configured"


def main() -> int:
    passed, reason = scan_frontend()
    print(("PASS" if passed else "FAIL") + " FRONTEND_BUNDLE_SECRET_SCAN: " + reason)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
