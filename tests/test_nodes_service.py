"""Unit tests for NodesService's read-only `sky status` snapshot."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from opc.plugins.office_ui.services.nodes import NodesService


class NodesServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_binary_not_found_reports_unavailable(self) -> None:
        service = NodesService()
        with patch("shutil.which", return_value=None):
            result = await service.list_nodes()
        self.assertFalse(result.payload["available"])
        self.assertEqual(result.payload["clusters"], [])

    async def test_parses_sky_status_json_output(self) -> None:
        service = NodesService()
        fake_output = (
            b'[{"name": "opc-worker-1", "status": "UP", "region": "us-east-1", '
            b'"instance_type": "m5.large", "price_per_hour": 0.096, "runtime_seconds": 3600}]'
        )
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(fake_output, b""))
        proc.returncode = 0
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await service.list_nodes()
        self.assertTrue(result.payload["available"])
        self.assertEqual(len(result.payload["clusters"]), 1)
        self.assertEqual(result.payload["clusters"][0]["name"], "opc-worker-1")
        self.assertEqual(result.payload["clusters"][0]["status"], "UP")

    async def test_subprocess_failure_reports_unavailable_not_raises(self) -> None:
        service = NodesService()
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"", b"sky: command failed"))
        proc.returncode = 1
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await service.list_nodes()
        self.assertFalse(result.payload["available"])
        self.assertEqual(result.payload["clusters"], [])

    async def test_invalid_json_reports_unavailable_not_raises(self) -> None:
        service = NodesService()
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"not json", b""))
        proc.returncode = 0
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await service.list_nodes()
        self.assertFalse(result.payload["available"])


if __name__ == "__main__":
    unittest.main()
