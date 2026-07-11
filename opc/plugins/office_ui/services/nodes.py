"""Read-only SkyPilot cluster status, shared by Office UI.

No lifecycle operations (start/stop/launch) live here on purpose — this round
only needs visibility into the local SkyPilot install, per the design spec's
explicit non-goal of per-user VM lifecycle management.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from .models import ServiceResult


class NodesService:
    async def list_nodes(self) -> ServiceResult:
        binary = shutil.which("sky")
        if not binary:
            return ServiceResult({"available": False, "clusters": []})

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "status", "-o", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await proc.communicate()
        except OSError:
            return ServiceResult({"available": False, "clusters": []})

        if proc.returncode != 0:
            return ServiceResult({"available": False, "clusters": []})

        try:
            raw_clusters = json.loads(stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return ServiceResult({"available": False, "clusters": []})

        if not isinstance(raw_clusters, list):
            return ServiceResult({"available": False, "clusters": []})

        clusters = [
            {
                "name": str(entry.get("name", "")),
                "status": str(entry.get("status", "")),
                "region": str(entry.get("region", "")),
                "instance_type": str(entry.get("instance_type", "")),
                "price_per_hour": entry.get("price_per_hour"),
                "runtime_seconds": entry.get("runtime_seconds"),
            }
            for entry in raw_clusters
            if isinstance(entry, dict)
        ]
        return ServiceResult({"available": True, "clusters": clusters})
