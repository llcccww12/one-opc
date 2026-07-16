"""Per-user SkyPilot VM lifecycle: launch/start + Claude Code CLI pre-install verification.

Unlike NodesService (read-only, shows every local SkyPilot cluster), this
service is scoped to "the caller's own VM" and performs write operations
(sky launch / sky start). One VM per user, keyed by user_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from opc.plugins.office_ui.tenant_vm_store import TenantVmStore

logger = logging.getLogger(__name__)

_LAUNCH_TIMEOUT_SECONDS = 600
_VERIFY_TIMEOUT_SECONDS = 60
_LIVENESS_CHECK_TIMEOUT_SECONDS = 20
_LIVENESS_CHECK_INTERVAL_SECONDS = 30
_STOP_TIMEOUT_SECONDS = 120
_STATUS_CACHE_TTL_SECONDS = 10
_IDLE_CHECK_INTERVAL_SECONDS = 300  # 5 minutes
_IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes
_TASK_YAML = Path(__file__).parent / "skypilot" / "tenant_vm.yaml"
# Passed to `sky launch --workdir` so the VM syncs this checkout's source tree
# without hardcoding one operator's local path into the shared tenant_vm.yaml.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Type alias for the broadcast callback used to push status changes to WS clients
_BroadcastFn = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class _LivenessUnknown(Exception):
    """sky status could not be queried; caller must leave the stored status untouched."""


def _cluster_name_for(user_id: str) -> str:
    return f"opc-tenant-{user_id[:12]}"


def _failure_message(stdout: bytes, stderr: bytes) -> str:
    # sky's CLI writes most human-readable errors to stdout (rich console
    # output), not stderr — prefer stderr when non-empty but fall back to
    # stdout so a real failure is never reported as a blank error message.
    text = stderr if stderr.strip() else stdout
    return text.decode("utf-8", errors="replace")[-2000:]


class TenantVmService:
    def __init__(self, store: TenantVmStore, control_plane_url: str = "") -> None:
        self._store = store
        self._control_plane_url = control_plane_url
        self._tasks: dict[str, asyncio.Task] = {}
        self._last_liveness_check: dict[str, float] = {}
        # Idle detection: last activity timestamp per user
        self._last_activity: dict[str, float] = {}
        # Status cache: (status_dict, timestamp) per user
        self._status_cache: dict[str, tuple[dict, float]] = {}
        # Broadcast callback for pushing status changes to WS clients
        self._broadcast: _BroadcastFn | None = None
        # Background task references
        self._idle_check_task: asyncio.Task | None = None

    def set_broadcast(self, broadcast: _BroadcastFn) -> None:
        """Set the broadcast callback for pushing vm_status_changed events."""
        self._broadcast = broadcast

    def start_idle_monitor(self) -> None:
        """Start the background idle-detection loop."""
        if self._idle_check_task is None or self._idle_check_task.done():
            self._idle_check_task = asyncio.create_task(self._idle_check_loop())

    def record_activity(self, user_id: str) -> None:
        """Update the last-activity timestamp for *user_id*."""
        self._last_activity[user_id] = time.monotonic()

    async def stop_vm(self, user_id: str) -> dict:
        """Stop the user's VM via ``sky stop``."""
        vm = await self._store.get_vm(user_id)
        if vm is None:
            return {"status": "none", "cluster_name": None, "error_message": "未绑定云主机"}
        if vm["status"] not in ("ready", "error"):
            return {"status": vm["status"], "cluster_name": vm["cluster_name"], "error_message": "当前状态无法停止"}

        cluster_name = vm["cluster_name"]
        await self._store.update_status(user_id, "stopping")
        await self._invalidate_cache(user_id)
        self._start_background(user_id, self._run_stop(user_id, cluster_name))
        return await self.get_status(user_id)

    async def start_vm(self, user_id: str) -> dict:
        """Start a stopped VM via ``sky launch -c <cluster>``."""
        vm = await self._store.get_vm(user_id)
        if vm is None:
            return {"status": "none", "cluster_name": None, "error_message": "未绑定云主机"}
        if vm["status"] != "stopped":
            return {"status": vm["status"], "cluster_name": vm["cluster_name"], "error_message": "当前状态无法启动"}

        cluster_name = vm["cluster_name"]
        await self._store.update_status(user_id, "launching")
        await self._invalidate_cache(user_id)
        self._start_background(user_id, self._run_start(user_id, cluster_name))
        return await self.get_status(user_id)

    async def _run_stop(self, user_id: str, cluster_name: str) -> None:
        binary = shutil.which("sky")
        if not binary:
            await self._store.update_status(user_id, "error", "未检测到 SkyPilot（sky 命令不存在）")
            await self._push_status_change(user_id)
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "stop", cluster_name, "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_STOP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "sky stop 超时")
            await self._push_status_change(user_id)
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky stop 启动失败: {exc}")
            await self._push_status_change(user_id)
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", _failure_message(stdout, stderr))
            await self._push_status_change(user_id)
            return

        await self._store.update_status(user_id, "stopped")
        await self._invalidate_cache(user_id)
        await self._push_status_change(user_id)

    async def _push_status_change(self, user_id: str) -> None:
        """Broadcast a vm_status_changed event to all WS clients."""
        if self._broadcast is None:
            return
        try:
            status = await self.get_status(user_id)
            await self._broadcast({
                "type": "vm_status_changed",
                "payload": {"user_id": user_id, **status},
            })
        except Exception:
            logger.debug("Failed to broadcast vm_status_changed for %s", user_id, exc_info=True)

    async def _invalidate_cache(self, user_id: str) -> None:
        self._status_cache.pop(user_id, None)

    async def _idle_check_loop(self) -> None:
        """Background loop that auto-stops VMs idle for >30 minutes."""
        while True:
            await asyncio.sleep(_IDLE_CHECK_INTERVAL_SECONDS)
            try:
                await self._check_idle_vms()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Idle check iteration failed", exc_info=True)

    async def _check_idle_vms(self) -> None:
        now = time.monotonic()
        # Snapshot keys to avoid mutation during iteration
        for user_id in list(self._last_activity.keys()):
            last = self._last_activity.get(user_id, 0.0)
            if now - last < _IDLE_TIMEOUT_SECONDS:
                continue
            try:
                vm = await self._store.get_vm(user_id)
                if vm is None or vm["status"] != "ready":
                    continue
                # VM has been idle for >30 minutes — auto-stop
                logger.info("Auto-stopping idle VM for user %s (idle %.0fs)", user_id, now - last)
                await self.stop_vm(user_id)
            except Exception:
                logger.debug("Auto-stop failed for user %s", user_id, exc_info=True)

    async def get_status(self, user_id: str, *, skip_cache: bool = False) -> dict:
        # Return cached status if fresh enough
        if not skip_cache and user_id in self._status_cache:
            cached, ts = self._status_cache[user_id]
            if time.monotonic() - ts < _STATUS_CACHE_TTL_SECONDS:
                return cached

        vm = await self._store.get_vm(user_id)
        if vm is None:
            result = {"status": "none", "cluster_name": None, "error_message": None}
            self._status_cache[user_id] = (result, time.monotonic())
            return result
        if vm["status"] in ("ready", "stopped"):
            vm = await self._reconcile_liveness(user_id, vm)
        result = {
            "status": vm["status"],
            "cluster_name": vm["cluster_name"],
            "error_message": vm["error_message"],
        }
        self._status_cache[user_id] = (result, time.monotonic())
        return result

    async def _reconcile_liveness(self, user_id: str, vm: dict) -> dict:
        last_checked = self._last_liveness_check.get(user_id, 0.0)
        now = time.monotonic()
        if now - last_checked < _LIVENESS_CHECK_INTERVAL_SECONDS:
            return vm
        self._last_liveness_check[user_id] = now

        try:
            sky_state = await self._check_cluster_state(vm["cluster_name"])
        except _LivenessUnknown:
            return vm

        if sky_state == "UP":
            new_status = "ready"
        elif sky_state == "STOPPED":
            new_status = "stopped"
        else:
            new_status = "error"

        if new_status == vm["status"]:
            return vm

        message = "云主机在 SkyPilot 侧已不存在，请重新创建" if new_status == "error" else None
        await self._store.update_status(user_id, new_status, message)
        await self._invalidate_cache(user_id)
        await self._push_status_change(user_id)
        return await self._store.get_vm(user_id)

    async def _check_cluster_state(self, cluster_name: str) -> str | None:
        binary = shutil.which("sky")
        if not binary:
            raise _LivenessUnknown("sky binary not found")

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "status", "-o", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=_LIVENESS_CHECK_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, OSError) as exc:
            raise _LivenessUnknown(str(exc)) from exc

        try:
            clusters = json.loads(stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise _LivenessUnknown(str(exc)) from exc

        if not isinstance(clusters, list):
            raise _LivenessUnknown("unexpected sky status output")

        for entry in clusters:
            if isinstance(entry, dict) and entry.get("name") == cluster_name:
                return entry.get("status")
        return None

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
            self.record_activity(user_id)
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return await self.get_status(user_id)

        if vm["status"] == "launching":
            return await self.get_status(user_id)

        if vm["status"] == "error":
            await self._store.update_status(user_id, "launching")
            self._start_background(user_id, self._run_launch(user_id, vm["cluster_name"]))
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return await self.get_status(user_id)

        if vm["status"] == "stopped":
            await self._store.update_status(user_id, "launching")
            self._start_background(user_id, self._run_start(user_id, vm["cluster_name"]))
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
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
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        vm = await self._store.get_vm(user_id)
        auth_token = vm["auth_token"]

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "launch", "-c", cluster_name, str(_TASK_YAML),
                "--workdir", str(_REPO_ROOT),
                "--env", f"OPC_CONTROL_PLANE_URL={self._control_plane_url}",
                "--env", f"OPC_WORKER_TOKEN={auth_token}",
                "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky launch 超过 10 分钟未完成）")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky launch 启动失败: {exc}")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", _failure_message(stdout, stderr))
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        await self._verify_and_finalize(user_id, cluster_name, binary)

    async def _run_start(self, user_id: str, cluster_name: str) -> None:
        binary = shutil.which("sky")
        if not binary:
            await self._store.update_status(user_id, "error", "未检测到 SkyPilot（sky 命令不存在）")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        vm = await self._store.get_vm(user_id)
        auth_token = vm["auth_token"]

        try:
            # `sky start` merely powers the VM back on — it does not accept
            # env vars and does not re-run the task's `run:` block, so the
            # opc worker process from before the stop would never come back.
            # `sky launch -c <existing cluster>` restarts a stopped cluster
            # AND re-runs setup/run (idempotent — setup mostly no-ops via
            # "already satisfied"), which is what's actually needed here.
            proc = await asyncio.create_subprocess_exec(
                binary, "launch", "-c", cluster_name, str(_TASK_YAML),
                "--workdir", str(_REPO_ROOT),
                "--env", f"OPC_CONTROL_PLANE_URL={self._control_plane_url}",
                "--env", f"OPC_WORKER_TOKEN={auth_token}",
                "-y",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky start 超过 10 分钟未完成）")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky start 启动失败: {exc}")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", _failure_message(stdout, stderr))
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
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
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"验证失败: {exc}")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        if proc.returncode != 0:
            message = _failure_message(stdout, stderr)
            await self._store.update_status(user_id, "error", f"验证失败: claude --version 执行失败: {message}")
            await self._invalidate_cache(user_id)
            await self._push_status_change(user_id)
            return

        await self._store.update_status(user_id, "ready")
        self.record_activity(user_id)
        await self._invalidate_cache(user_id)
        await self._push_status_change(user_id)
