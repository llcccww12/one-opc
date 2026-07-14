"""Per-user SkyPilot VM lifecycle: launch/start + Claude Code CLI pre-install verification.

Unlike NodesService (read-only, shows every local SkyPilot cluster), this
service is scoped to "the caller's own VM" and performs write operations
(sky launch / sky start). One VM per user, keyed by user_id.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
from pathlib import Path

from opc.plugins.office_ui.tenant_vm_store import TenantVmStore

_LAUNCH_TIMEOUT_SECONDS = 600
_VERIFY_TIMEOUT_SECONDS = 60
_TASK_YAML = Path(__file__).parent / "skypilot" / "tenant_vm.yaml"


def _cluster_name_for(user_id: str) -> str:
    return f"opc-tenant-{user_id[:12]}"


def _failure_message(stdout: bytes, stderr: bytes) -> str:
    # sky's CLI writes most human-readable errors to stdout (rich console
    # output), not stderr — prefer stderr when non-empty but fall back to
    # stdout so a real failure is never reported as a blank error message.
    text = stderr if stderr.strip() else stdout
    return text.decode("utf-8", errors="replace")[-2000:]


class TenantVmService:
    def __init__(self, store: TenantVmStore) -> None:
        self._store = store
        self._tasks: dict[str, asyncio.Task] = {}

    async def get_status(self, user_id: str) -> dict:
        vm = await self._store.get_vm(user_id)
        if vm is None:
            return {"status": "none", "cluster_name": None, "error_message": None}
        return {
            "status": vm["status"],
            "cluster_name": vm["cluster_name"],
            "error_message": vm["error_message"],
        }

    async def recover_from_restart(self) -> None:
        """Reset any 'launching' rows left behind by a prior process (crash
        or restart) since their in-memory asyncio.Task no longer exists."""
        await self._store.reset_stale_launching()

    async def bind(self, user_id: str) -> dict:
        vm = await self._store.get_vm(user_id)

        if vm is None:
            cluster_name = _cluster_name_for(user_id)
            auth_token = secrets.token_urlsafe(32)
            await self._store.create_vm(user_id, cluster_name, auth_token)
            self._start_background(user_id, self._run_launch(user_id, cluster_name))
            return await self.get_status(user_id)

        if vm["status"] == "launching":
            return await self.get_status(user_id)

        if vm["status"] == "error":
            await self._store.update_status(user_id, "launching")
            self._start_background(user_id, self._run_launch(user_id, vm["cluster_name"]))
            return await self.get_status(user_id)

        if vm["status"] == "stopped":
            await self._store.update_status(user_id, "launching")
            self._start_background(user_id, self._run_start(user_id, vm["cluster_name"]))
            return await self.get_status(user_id)

        return await self.get_status(user_id)

    def _start_background(self, user_id: str, coro) -> None:
        existing = self._tasks.get(user_id)
        if existing is not None and not existing.done():
            return
        self._tasks[user_id] = asyncio.create_task(coro)

    async def _run_launch(self, user_id: str, cluster_name: str) -> None:
        binary = shutil.which("sky")
        if not binary:
            await self._store.update_status(user_id, "error", "未检测到 SkyPilot（sky 命令不存在）")
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "launch", "-c", cluster_name, str(_TASK_YAML), "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky launch 超过 10 分钟未完成）")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky launch 启动失败: {exc}")
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", _failure_message(stdout, stderr))
            return

        await self._verify_and_finalize(user_id, cluster_name, binary)

    async def _run_start(self, user_id: str, cluster_name: str) -> None:
        binary = shutil.which("sky")
        if not binary:
            await self._store.update_status(user_id, "error", "未检测到 SkyPilot（sky 命令不存在）")
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "start", cluster_name, "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky start 超过 10 分钟未完成）")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky start 启动失败: {exc}")
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", _failure_message(stdout, stderr))
            return

        await self._verify_and_finalize(user_id, cluster_name, binary)

    async def _verify_and_finalize(self, user_id: str, cluster_name: str, binary: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "exec", cluster_name, "claude --version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_VERIFY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "验证超时: claude --version 未在 60 秒内完成")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"验证失败: {exc}")
            return

        if proc.returncode != 0:
            message = _failure_message(stdout, stderr)
            await self._store.update_status(user_id, "error", f"验证失败: claude --version 执行失败: {message}")
            return

        await self._store.update_status(user_id, "ready")
