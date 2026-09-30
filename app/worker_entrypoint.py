"""Dedicated process entrypoint for Railway's durable worker service."""
from __future__ import annotations

import asyncio
import os
import signal
from uuid import uuid4

from .simulation_worker import periodic_recovery, recovery_cycle
from . import database, crypto


async def main() -> None:
    if os.getenv("SERVICE_ROLE", "").strip().lower() != "worker":
        raise RuntimeError("Dedicated worker requires SERVICE_ROLE=worker.")
    if database.APP_CONFIG.deployment_profile != "hosted_topstep_combine_beta":
        raise RuntimeError("Dedicated hosted-beta worker requires the approved hosted profile.")
    if os.getenv("PROVIDER_MUTATIONS_ENABLED", "false").strip().lower() != "false":
        raise RuntimeError("Provider mutation capabilities must remain disabled.")
    if database.APP_CONFIG.is_production and not crypto.key_management_health().get("available"):
        raise RuntimeError("Worker key-management readiness failed closed.")
    worker_id = f"railway-durable-worker:{uuid4().hex}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await asyncio.to_thread(recovery_cycle, worker_id=worker_id)
    await periodic_recovery(stop, worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(main())
