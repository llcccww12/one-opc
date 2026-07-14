"""Unit tests for TenantVmService's sky launch/start + Claude Code CLI verification."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

from opc.plugins.office_ui.tenant_vm_service import TenantVmService
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore


def _make_proc(returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TenantVmServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = TenantVmStore(self.db)
        await self.store.initialize()
        self.service = TenantVmService(self.store)

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_bind_new_user_creates_record_and_launches_to_ready(self) -> None:
        launch_proc = _make_proc(0)
        verify_proc = _make_proc(0, stdout=b"1.0.0")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=[launch_proc, verify_proc])):
            result = await self.service.bind("user-1")
            self.assertEqual(result["status"], "launching")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "ready")

    async def test_bind_reports_error_when_sky_launch_fails(self) -> None:
        launch_proc = _make_proc(1, stderr=b"quota exceeded")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=launch_proc)):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIn("quota exceeded", final["error_message"])

    async def test_bind_reports_error_when_verification_fails(self) -> None:
        launch_proc = _make_proc(0)
        verify_proc = _make_proc(1, stderr=b"claude: command not found")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=[launch_proc, verify_proc])):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIn("claude: command not found", final["error_message"])

    async def test_bind_reports_error_when_sky_binary_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIn("SkyPilot", final["error_message"])

    async def test_bind_while_already_launching_does_not_start_second_task(self) -> None:
        with patch.object(TenantVmService, "_start_background") as start_mock:
            await self.service.bind("user-1")
            await self.service.bind("user-1")
        self.assertEqual(start_mock.call_count, 1)

    async def test_bind_on_stopped_vm_calls_sky_start_not_launch(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "stopped")
        start_proc = _make_proc(0)
        verify_proc = _make_proc(0, stdout=b"1.0.0")
        create_subprocess_mock = AsyncMock(side_effect=[start_proc, verify_proc])
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", create_subprocess_mock):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        args, _kwargs = create_subprocess_mock.await_args_list[0]
        self.assertIn("start", args)
        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "ready")

    async def test_bind_on_ready_vm_is_a_noop(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        with patch("asyncio.create_subprocess_exec") as create_subprocess_mock:
            result = await self.service.bind("user-1")
        create_subprocess_mock.assert_not_called()
        self.assertEqual(result["status"], "ready")

    async def test_get_status_returns_none_when_unrecorded(self) -> None:
        result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "none")
        self.assertIsNone(result["cluster_name"])


class TenantVmTaskYamlTests(unittest.TestCase):
    def test_task_yaml_is_valid_and_installs_claude_cli(self) -> None:
        import yaml

        from opc.plugins.office_ui.tenant_vm_service import _TASK_YAML

        with open(_TASK_YAML, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.assertIn("setup", doc)
        self.assertIn("@anthropic-ai/claude-code", doc["setup"])


if __name__ == "__main__":
    unittest.main()
