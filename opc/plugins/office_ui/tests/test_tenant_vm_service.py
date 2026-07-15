"""Unit tests for TenantVmService's sky launch/start + Claude Code CLI verification."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

from opc.plugins.office_ui.tenant_vm_service import TenantVmService, _cluster_name_for, _REPO_ROOT
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
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": _cluster_name_for("user-1"), "status": "UP"}]
        ).encode())
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=[launch_proc, verify_proc, status_proc])):
            result = await self.service.bind("user-1")
            self.assertEqual(result["status"], "launching")
            await self.service._tasks["user-1"]
            final = await self.service.get_status("user-1")

        self.assertEqual(final["status"], "ready")

    async def test_bind_new_user_passes_repo_root_as_workdir(self) -> None:
        # tenant_vm.yaml deliberately has no static `workdir:` field (that
        # would hardcode one operator's local path into a shared config
        # file) — the repo root must be passed via --workdir instead.
        launch_proc = _make_proc(0)
        verify_proc = _make_proc(0, stdout=b"1.0.0")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": _cluster_name_for("user-1"), "status": "UP"}]
        ).encode())
        create_subprocess_mock = AsyncMock(side_effect=[launch_proc, verify_proc, status_proc])
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", create_subprocess_mock):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        args, _kwargs = create_subprocess_mock.await_args_list[0]
        workdir_index = args.index("--workdir")
        self.assertEqual(args[workdir_index + 1], str(_REPO_ROOT))

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

    async def test_bind_reports_error_from_stdout_when_stderr_is_empty(self) -> None:
        # sky's CLI writes most human-readable errors to stdout (rich console
        # output), not stderr — a real EACCES npm failure surfaces this way.
        launch_proc = _make_proc(1, stdout=b"npm error EACCES: permission denied", stderr=b"")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=launch_proc)):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIn("EACCES", final["error_message"])

    async def test_bind_reports_error_when_sky_binary_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIn("SkyPilot", final["error_message"])

    async def test_bind_while_already_launching_does_not_start_second_task(self) -> None:
        def _close_coro(user_id, coro):
            coro.close()

        with patch.object(TenantVmService, "_start_background", side_effect=_close_coro) as start_mock:
            await self.service.bind("user-1")
            await self.service.bind("user-1")
        self.assertEqual(start_mock.call_count, 1)

    async def test_bind_on_stopped_vm_calls_sky_launch_to_resume(self) -> None:
        # sky start alone can't re-run the task's run: block (no env vars,
        # doesn't restart opc worker) — resuming a stopped VM goes through
        # sky launch -c <existing cluster> just like a fresh bind.
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "stopped")
        start_proc = _make_proc(0)
        verify_proc = _make_proc(0, stdout=b"1.0.0")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": "opc-tenant-abc123", "status": "UP"}]
        ).encode())
        create_subprocess_mock = AsyncMock(side_effect=[start_proc, verify_proc, status_proc])
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", create_subprocess_mock):
            await self.service.bind("user-1")
            await self.service._tasks["user-1"]

            args, _kwargs = create_subprocess_mock.await_args_list[0]
            self.assertIn("launch", args)
            self.assertIn("-c", args)
            self.assertIn("--env", args)
            final = await self.service.get_status("user-1")

        self.assertEqual(final["status"], "ready")

    async def test_bind_on_ready_vm_is_a_noop(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": "opc-tenant-abc123", "status": "UP"}]
        ).encode())
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=status_proc)) as create_subprocess_mock:
            result = await self.service.bind("user-1")
        for call in create_subprocess_mock.await_args_list:
            self.assertNotIn("launch", call.args)
            self.assertNotIn("start", call.args)
        self.assertEqual(result["status"], "ready")

    async def test_get_status_returns_none_when_unrecorded(self) -> None:
        result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "none")
        self.assertIsNone(result["cluster_name"])

    async def test_get_status_keeps_ready_when_sky_reports_cluster_up(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": "opc-tenant-abc123", "status": "UP"}]
        ).encode())
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=status_proc)):
            result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "ready")

    async def test_get_status_downgrades_ready_to_stopped_when_sky_reports_stopped(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": "opc-tenant-abc123", "status": "STOPPED"}]
        ).encode())
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=status_proc)):
            result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "stopped")

    async def test_get_status_downgrades_ready_to_error_when_cluster_missing(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(0, stdout=b"[]")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=status_proc)):
            result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error_message"])

    async def test_get_status_throttles_liveness_check_within_interval(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(0, stdout=json.dumps(
            [{"name": "opc-tenant-abc123", "status": "UP"}]
        ).encode())
        create_subprocess_mock = AsyncMock(return_value=status_proc)
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", create_subprocess_mock):
            await self.service.get_status("user-1")
            await self.service.get_status("user-1")
        self.assertEqual(create_subprocess_mock.await_count, 1)

    async def test_get_status_leaves_status_untouched_when_sky_status_fails(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        status_proc = _make_proc(1, stdout=b"not json")
        with patch("shutil.which", return_value="/usr/local/bin/sky"), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=status_proc)):
            result = await self.service.get_status("user-1")
        self.assertEqual(result["status"], "ready")

    async def test_recover_from_restart_marks_stale_launching_vm_as_error(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")

        await self.service.recover_from_restart()

        final = await self.service.get_status("user-1")
        self.assertEqual(final["status"], "error")
        self.assertIsNotNone(final["error_message"])


class TenantVmTaskYamlTests(unittest.TestCase):
    def test_task_yaml_is_valid_and_installs_claude_cli(self) -> None:
        import yaml

        from opc.plugins.office_ui.tenant_vm_service import _TASK_YAML

        with open(_TASK_YAML, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.assertIn("setup", doc)
        self.assertIn("@anthropic-ai/claude-code", doc["setup"])
        self.assertIn("sudo npm install -g @anthropic-ai/claude-code", doc["setup"])


if __name__ == "__main__":
    unittest.main()
