# 每用户 SkyPilot 云主机：生命周期管理 + 绑定页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a logged-in user a way to bind their own per-user SkyPilot VM (AWS), which comes up with the Claude Code CLI pre-installed and verified (`claude --version`), and gate entry into the workspace on that VM being `ready`.

**Architecture:** A new `TenantVmStore` (mirrors `UserStore`'s sqlite-in-`ui_state.db` pattern) persists one VM record per `user_id`. A new `TenantVmService` wraps `sky launch`/`sky start`/`sky exec` as background `asyncio.create_task` work (mirrors `NodesService`'s subprocess pattern, but this one writes instead of just reading) and is exposed via two new plain-HTTP routes (`POST /api/vm/bind`, `GET /api/vm/status`) — the same REST family as `/api/register`/`/api/login`, not the WS-request-type family used by the rest of the app post-login. On the frontend, `Root.tsx` grows a third gate state: unauthenticated → `LoginScreen`; authenticated but VM not `ready` → new `BindNodePage`; VM `ready` → existing `App`.

**Tech Stack:** Python 3.10+, aiohttp (existing), aiosqlite (existing), stdlib `asyncio`/`shutil`/`secrets` (no new dependency). React 19 + TypeScript on the frontend, zero test framework (`tsx` + `node:assert/strict`).

## Global Constraints

- Scope is **only**: VM record persistence, `sky launch`/`sky start` orchestration, Claude Code CLI install + `claude --version` verification, the two REST routes, and the binding-page frontend gate. `opc worker` mode, per-user credential vault (BYOK), and worker↔control-plane data relay are separate follow-up plans — do not implement them here (per `docs/superpowers/specs/2026-07-12-tenant-vm-lifecycle-binding-design.md`, "非目标").
- One VM per user (`user_id` is the primary key of the new table) — no multi-VM-per-user support.
- Cluster naming: `opc-tenant-<user_id 前12位>`. `user_id` is a `secrets.token_hex(16)` hex string (from `UserStore.register`), so slicing the first 12 chars is always alphanumeric and safe as a SkyPilot cluster-name component.
- CLI install target is Claude Code only (`npm install -g @anthropic-ai/claude-code`) — no other agent adapters this round.
- No CLI authentication/login flow this round — `claude --version` does not require an API key. Per-user key injection is the next sub-project's scope.
- No idle auto-suspend (`sky stop` triggered by inactivity) this round — there is no real task activity signal yet to key it off.
- Background operations (`sky launch`/`sky start`/`sky exec`) run under a 600s (`launch`/`start`) or 60s (`exec` verify) `asyncio.wait_for` timeout; a timeout is treated as `status="error"`, never left hanging.
- Backend tests run with `python -m pytest opc/plugins/office_ui/tests/<file>.py -q` (matches where `test_user_store.py`/`test_auth_routes.py` already live — this feature's new files live alongside them in `opc/plugins/office_ui/`, not in top-level `tests/`).
- Frontend tests run with `npx tsx <file>.test.ts(x)` from `opc/plugins/office_ui/frontend_src` — no DOM renderer in this repo; components that touch browser globals are tested by reading their own source with `readFileSync` and asserting key call-sites via `assert.match(source, /regex/)`, per `auth/LoginScreen.test.tsx`. Pure-function modules (no browser globals) get real executable tests with a mocked `fetch`, per `lib/auth.test.ts`.
- `lib/vm.ts`'s functions take the session token as an explicit parameter (not read internally via `getStoredToken()`) — this keeps the module a pure, browser-global-free function like `auth.ts`'s `postAuth`, testable under plain Node without mocking `window`. Only the React components (`BindNodePage`, `Root`) call `getStoredToken()` and pass the value in.
- This is a security/infra feature touching real cloud spend — the final task requires a real AWS-backed `sky launch` run, not just mocked unit tests.

---

### Task 1: `TenantVmStore` — VM lifecycle persistence

**Files:**
- Create: `opc/plugins/office_ui/tenant_vm_store.py`
- Test: `opc/plugins/office_ui/tests/test_tenant_vm_store.py`

**Interfaces:**
- Produces: `class TenantVmStore` with `__init__(self, db: aiosqlite.Connection) -> None`, `async def initialize(self) -> None`, `async def get_vm(self, user_id: str) -> dict | None` (keys: `cluster_name`, `status`, `auth_token`, `error_message`, `created_at`, `updated_at`), `async def create_vm(self, user_id: str, cluster_name: str, auth_token: str) -> None` (inserts with `status="launching"`, `error_message=NULL`), `async def update_status(self, user_id: str, status: str, error_message: str | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_tenant_vm_store.py`:

```python
from __future__ import annotations

import unittest

import aiosqlite

from opc.plugins.office_ui.tenant_vm_store import TenantVmStore


class TenantVmStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = TenantVmStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_get_vm_returns_none_when_unrecorded(self) -> None:
        vm = await self.store.get_vm("user-1")
        self.assertIsNone(vm)

    async def test_create_then_get_vm_round_trips(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        vm = await self.store.get_vm("user-1")
        self.assertIsNotNone(vm)
        self.assertEqual(vm["cluster_name"], "opc-tenant-abc123")
        self.assertEqual(vm["status"], "launching")
        self.assertEqual(vm["auth_token"], "tok-abc")
        self.assertIsNone(vm["error_message"])

    async def test_update_status_changes_status_and_error_message(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "error", "sky launch failed")
        vm = await self.store.get_vm("user-1")
        self.assertEqual(vm["status"], "error")
        self.assertEqual(vm["error_message"], "sky launch failed")

    async def test_update_status_to_ready_clears_previous_error(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "error", "boom")
        await self.store.update_status("user-1", "ready")
        vm = await self.store.get_vm("user-1")
        self.assertEqual(vm["status"], "ready")
        self.assertIsNone(vm["error_message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.tenant_vm_store'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/tenant_vm_store.py`:

```python
"""SQLite-backed store for per-user SkyPilot VM lifecycle state.

Mirrors the UserStore/AgentStore pattern: the connection is opened once by
the caller (server.py) and shared; initialize() only ever CREATEs. One VM
per user — user_id is the primary key.
"""

from __future__ import annotations

import asyncio
import time

import aiosqlite


class TenantVmStore:
    """Persists one SkyPilot VM record per user in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_vms (
                user_id TEXT PRIMARY KEY,
                cluster_name TEXT NOT NULL,
                status TEXT NOT NULL,
                auth_token TEXT,
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def get_vm(self, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT cluster_name, status, auth_token, error_message, created_at, updated_at "
            "FROM tenant_vms WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "cluster_name": row[0],
            "status": row[1],
            "auth_token": row[2],
            "error_message": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

    async def create_vm(self, user_id: str, cluster_name: str, auth_token: str) -> None:
        async with self._write_lock:
            now = time.time()
            await self._db.execute(
                "INSERT INTO tenant_vms "
                "(user_id, cluster_name, status, auth_token, error_message, created_at, updated_at) "
                "VALUES (?, ?, 'launching', ?, NULL, ?, ?)",
                (user_id, cluster_name, auth_token, now, now),
            )
            await self._db.commit()

    async def update_status(self, user_id: str, status: str, error_message: str | None = None) -> None:
        async with self._write_lock:
            await self._db.execute(
                "UPDATE tenant_vms SET status = ?, error_message = ?, updated_at = ? WHERE user_id = ?",
                (status, error_message, time.time(), user_id),
            )
            await self._db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_store.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/tenant_vm_store.py opc/plugins/office_ui/tests/test_tenant_vm_store.py
git commit -m "feat: add TenantVmStore for per-user SkyPilot VM lifecycle persistence"
```

---

### Task 2: `TenantVmService` — launch/start orchestration + Claude Code CLI verification

**Files:**
- Create: `opc/plugins/office_ui/tenant_vm_service.py`
- Create: `opc/plugins/office_ui/skypilot/tenant_vm.yaml`
- Test: `opc/plugins/office_ui/tests/test_tenant_vm_service.py`

**Interfaces:**
- Consumes: `TenantVmStore.get_vm`/`create_vm`/`update_status` (Task 1).
- Produces: `class TenantVmService` with `__init__(self, store: TenantVmStore) -> None`, `async def get_status(self, user_id: str) -> dict` (keys: `status`, `cluster_name`, `error_message`; `status="none"` when no record exists), `async def bind(self, user_id: str) -> dict` (same shape as `get_status`; creates a record + kicks a background task if none exists, retries via `sky launch` if `status="error"`, resumes via `sky start` if `status="stopped"`, no-ops if `status in ("launching", "ready")`). The background task per user is tracked in `self._tasks: dict[str, asyncio.Task]` (tests await it directly via `service._tasks[user_id]`).

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/skypilot/tenant_vm.yaml` first (needed by the test file's YAML-validity check):

```yaml
resources:
  cloud: aws
  cpus: 2+
  disk_size: 50

setup: |
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
  npm install -g @anthropic-ai/claude-code

run: |
  echo "tenant VM ready"
```

Create `opc/plugins/office_ui/tests/test_tenant_vm_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.tenant_vm_service'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/tenant_vm_service.py`:

```python
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
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky launch 超过 10 分钟未完成）")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky launch 启动失败: {exc}")
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", stderr.decode("utf-8", errors="replace")[-2000:])
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
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_LAUNCH_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "操作超时（sky start 超过 10 分钟未完成）")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"sky start 启动失败: {exc}")
            return

        if proc.returncode != 0:
            await self._store.update_status(user_id, "error", stderr.decode("utf-8", errors="replace")[-2000:])
            return

        await self._verify_and_finalize(user_id, cluster_name, binary)

    async def _verify_and_finalize(self, user_id: str, cluster_name: str, binary: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "exec", cluster_name, "claude --version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_VERIFY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self._store.update_status(user_id, "error", "验证超时: claude --version 未在 60 秒内完成")
            return
        except OSError as exc:
            await self._store.update_status(user_id, "error", f"验证失败: {exc}")
            return

        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="replace")[-2000:]
            await self._store.update_status(user_id, "error", f"验证失败: claude --version 执行失败: {message}")
            return

        await self._store.update_status(user_id, "ready")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_service.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/tenant_vm_service.py opc/plugins/office_ui/skypilot/tenant_vm.yaml opc/plugins/office_ui/tests/test_tenant_vm_service.py
git commit -m "feat: add TenantVmService for sky launch/start + Claude Code CLI verification"
```

---

### Task 3: `/api/vm/bind` and `/api/vm/status` HTTP routes

**Files:**
- Create: `opc/plugins/office_ui/bind_routes.py`
- Test: `opc/plugins/office_ui/tests/test_bind_routes.py`

**Interfaces:**
- Consumes: `UserStore.get_user_id_for_token` (existing), `TenantVmService.bind`/`get_status` (Task 2).
- Produces: `make_bind_vm_handler(user_store: UserStore, vm_service: TenantVmService) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]` and `make_vm_status_handler(user_store: UserStore, vm_service: TenantVmService) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]`. Both require `Authorization: Bearer <token>`; respond `{"ok": true, "status": ..., "cluster_name": ..., "error_message": ...}` (200) or `{"ok": false, "error": "unauthorized"}` (401).

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/tests/test_bind_routes.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

import aiosqlite
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from opc.plugins.office_ui.bind_routes import make_bind_vm_handler, make_vm_status_handler
from opc.plugins.office_ui.tenant_vm_service import TenantVmService
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore
from opc.plugins.office_ui.user_store import UserStore


class BindRoutesTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.user_db = await aiosqlite.connect(":memory:")
        self.user_store = UserStore(self.user_db)
        await self.user_store.initialize()
        await self.user_store.create_invite_code("INVITE1")
        user_id, _err = await self.user_store.register("alice", "INVITE1")
        self.token = await self.user_store.create_session(user_id)

        self.vm_db = await aiosqlite.connect(":memory:")
        vm_store = TenantVmStore(self.vm_db)
        await vm_store.initialize()
        self.vm_service = TenantVmService(vm_store)
        self.vm_service.bind = AsyncMock(
            return_value={"status": "launching", "cluster_name": "opc-tenant-abc", "error_message": None}
        )
        self.vm_service.get_status = AsyncMock(
            return_value={"status": "none", "cluster_name": None, "error_message": None}
        )

        app = web.Application()
        app.router.add_post("/api/vm/bind", make_bind_vm_handler(self.user_store, self.vm_service))
        app.router.add_get("/api/vm/status", make_vm_status_handler(self.user_store, self.vm_service))
        return app

    async def tearDownAsync(self) -> None:
        await self.user_db.close()
        await self.vm_db.close()
        await super().tearDownAsync()

    async def test_bind_without_token_returns_401(self) -> None:
        resp = await self.client.post("/api/vm/bind")
        self.assertEqual(resp.status, 401)

    async def test_bind_with_invalid_token_returns_401(self) -> None:
        resp = await self.client.post("/api/vm/bind", headers={"Authorization": "Bearer not-a-real-token"})
        self.assertEqual(resp.status, 401)

    async def test_bind_with_valid_token_calls_service_and_returns_status(self) -> None:
        resp = await self.client.post("/api/vm/bind", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "launching")
        self.assertEqual(data["cluster_name"], "opc-tenant-abc")
        self.vm_service.bind.assert_awaited_once()

    async def test_status_without_token_returns_401(self) -> None:
        resp = await self.client.get("/api/vm/status")
        self.assertEqual(resp.status, 401)

    async def test_status_with_valid_token_returns_current_status(self) -> None:
        resp = await self.client.get("/api/vm/status", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "none")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_bind_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.bind_routes'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/bind_routes.py`:

```python
"""HTTP handlers for per-user SkyPilot VM binding (POST /api/vm/bind, GET /api/vm/status)."""

from __future__ import annotations

import aiohttp.web

from opc.plugins.office_ui.tenant_vm_service import TenantVmService
from opc.plugins.office_ui.user_store import UserStore


async def _authenticate_bearer(request: aiohttp.web.Request, user_store: UserStore) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    if not token:
        return None
    return await user_store.get_user_id_for_token(token)


def make_bind_vm_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.bind(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle


def make_vm_status_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.get_status(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_bind_routes.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/bind_routes.py opc/plugins/office_ui/tests/test_bind_routes.py
git commit -m "feat: add /api/vm/bind and /api/vm/status HTTP routes"
```

---

### Task 4: Wire `TenantVmStore`/`TenantVmService`/routes into `server.py`

**Files:**
- Modify: `opc/plugins/office_ui/server.py`

**Interfaces:**
- Consumes: `TenantVmStore` (Task 1), `TenantVmService` (Task 2), `make_bind_vm_handler`/`make_vm_status_handler` (Task 3).
- Produces: `app["tenant_vm_service"]` available on the running `aiohttp.web.Application`; `/api/vm/bind` and `/api/vm/status` reachable on the real server.

**Why this task has no dedicated new automated test:** identical reasoning to the account-system plan's Task 4 — `create_app()` unconditionally boots a real `OPCEngine`, and there's no lighter seam to inject fakes just to assert two `add_post`/`add_get` calls happened. This task is covered by Step 2's full regression run (which constructs real `WSHandler`/`ChatStore`/`UserStore` objects and would fail on an import/wiring mistake) and Task 5's manual walkthrough, which exercises the real routes end-to-end.

- [ ] **Step 1: Write the implementation**

In `opc/plugins/office_ui/server.py`, add imports right after the existing `from opc.plugins.office_ui.user_store import UserStore` line (line 27):

```python
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore
from opc.plugins.office_ui.tenant_vm_service import TenantVmService
from opc.plugins.office_ui.bind_routes import make_bind_vm_handler, make_vm_status_handler
```

After the existing block:

```python
    user_store = UserStore(db)
    await user_store.initialize()
```

insert:

```python

    tenant_vm_store = TenantVmStore(db)
    await tenant_vm_store.initialize()
    tenant_vm_service = TenantVmService(tenant_vm_store)
```

In the "Store references for cleanup" block, add `app["tenant_vm_service"] = tenant_vm_service` right after the existing `app["user_store"] = user_store` line.

In the "Routes" block, insert the new routes right after the existing register/login block:

```python
    app.router.add_post("/api/register", make_register_handler(user_store))
    app.router.add_post("/api/login", make_login_handler(user_store))

    # Per-user SkyPilot VM binding (must be registered before the SPA catch-all)
    app.router.add_post("/api/vm/bind", make_bind_vm_handler(user_store, tenant_vm_service))
    app.router.add_get("/api/vm/status", make_vm_status_handler(user_store, tenant_vm_service))
```

- [ ] **Step 2: Run the existing regression suite**

Run: `python -m pytest opc/plugins/office_ui/tests/ -v`
Expected: all PASS — confirms the new imports and constructor calls didn't break anything already covered.

- [ ] **Step 3: Commit**

```bash
git add opc/plugins/office_ui/server.py
git commit -m "feat: wire TenantVmStore/TenantVmService and /api/vm/bind, /api/vm/status into the office-UI server"
```

---

### Task 5: Frontend `lib/vm.ts` — status/bind API calls

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/lib/vm.ts`
- Test: `opc/plugins/office_ui/frontend_src/lib/vm.test.ts`

**Interfaces:**
- Produces: `interface VmStatus { status: 'none' | 'launching' | 'ready' | 'stopped' | 'error'; cluster_name: string | null; error_message: string | null }`, `getVmStatus(token: string): Promise<VmStatus>`, `bindVm(token: string): Promise<VmStatus>`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/lib/vm.test.ts`:

```ts
// Runs with `tsx` against node:assert/strict — matches repo convention for
// zero-framework tests. Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/vm.test.ts`
import assert from 'node:assert/strict'
import { getVmStatus, bindVm } from './vm'

async function run(): Promise<void> {
  let capturedUrl = ''
  let capturedMethod = ''
  let capturedAuth = ''
  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedMethod = init.method as string
    capturedAuth = (init.headers as Record<string, string>).Authorization
    return {
      ok: true,
      json: async () => ({ ok: true, status: 'launching', cluster_name: 'opc-tenant-abc', error_message: null }),
    }
  }

  const bound = await bindVm('tok123')
  assert.equal(capturedUrl, '/api/vm/bind')
  assert.equal(capturedMethod, 'POST')
  assert.equal(capturedAuth, 'Bearer tok123')
  assert.equal(bound.status, 'launching')
  assert.equal(bound.cluster_name, 'opc-tenant-abc')

  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedMethod = init.method as string
    return {
      ok: true,
      json: async () => ({ ok: true, status: 'ready', cluster_name: 'opc-tenant-abc', error_message: null }),
    }
  }
  const status = await getVmStatus('tok123')
  assert.equal(capturedUrl, '/api/vm/status')
  assert.equal(capturedMethod, 'GET')
  assert.equal(status.status, 'ready')

  ;(globalThis as any).fetch = async () => ({
    ok: false,
    json: async () => ({ ok: false, error: 'unauthorized' }),
  })
  const failed = await getVmStatus('bad-token')
  assert.equal(failed.status, 'error')
  assert.equal(failed.error_message, 'unauthorized')

  console.log('vm.test.ts passed')
}

run()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/vm.test.ts`
Expected: FAIL — `Cannot find module './vm'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/frontend_src/lib/vm.ts`:

```ts
export interface VmStatus {
  status: 'none' | 'launching' | 'ready' | 'stopped' | 'error'
  cluster_name: string | null
  error_message: string | null
}

async function callVmApi(path: string, method: 'GET' | 'POST', token: string): Promise<VmStatus> {
  try {
    const res = await fetch(path, {
      method,
      headers: { Authorization: `Bearer ${token}` },
    })
    const data = await res.json()
    if (!res.ok || !data.ok) {
      return { status: 'error', cluster_name: null, error_message: data.error ?? '请求失败' }
    }
    return {
      status: data.status,
      cluster_name: data.cluster_name ?? null,
      error_message: data.error_message ?? null,
    }
  } catch {
    return { status: 'error', cluster_name: null, error_message: '网络错误' }
  }
}

export function getVmStatus(token: string): Promise<VmStatus> {
  return callVmApi('/api/vm/status', 'GET', token)
}

export function bindVm(token: string): Promise<VmStatus> {
  return callVmApi('/api/vm/bind', 'POST', token)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/vm.test.ts`
Expected: `vm.test.ts passed` printed, exit code 0

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/lib/vm.ts opc/plugins/office_ui/frontend_src/lib/vm.test.ts
git commit -m "feat: add frontend getVmStatus/bindVm API calls"
```

---

### Task 6: `BindNodePage` component

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/auth/BindNodePage.tsx`
- Test: `opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`

**Interfaces:**
- Consumes: `getStoredToken` (`../lib/auth`, existing), `getVmStatus`/`bindVm`/`VmStatus` (`../lib/vm`, Task 5). Reuses `auth.css`'s `.auth-screen`/`.auth-form`/`.auth-error` classes (already exist, created for `LoginScreen`).
- Produces: `export function BindNodePage({ onReady }: { onReady: () => void }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`:

```ts
// Source-text regex test — matches the LoginScreen.test.tsx convention for
// components that reference browser globals and can't be rendered under
// plain Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'BindNodePage.tsx'), 'utf-8')

assert.match(source, /bindVm\(token\)/, 'BindNodePage must call bindVm() to trigger launch/start')
assert.match(source, /getVmStatus\(token\)/, 'BindNodePage must poll getVmStatus() for progress')
assert.match(source, /onReady\(\)/, 'BindNodePage must notify its parent once the VM is ready')
assert.match(source, /setInterval\(refresh, POLL_INTERVAL_MS\)/, 'BindNodePage must poll while launching')
assert.match(source, /clearInterval\(/, 'BindNodePage must stop polling once resolved')

console.log('BindNodePage.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`
Expected: FAIL — `ENOENT: no such file or directory ... BindNodePage.tsx`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/frontend_src/auth/BindNodePage.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { getStoredToken } from '../lib/auth'
import { bindVm, getVmStatus, type VmStatus } from '../lib/vm'
import './auth.css'

interface BindNodePageProps {
  onReady: () => void
}

const POLL_INTERVAL_MS = 5000

export function BindNodePage({ onReady }: BindNodePageProps) {
  const [vmStatus, setVmStatus] = useState<VmStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const refresh = async () => {
    const token = getStoredToken()
    if (!token) return
    const result = await getVmStatus(token)
    setVmStatus(result)
    if (result.status === 'ready') {
      stopPolling()
    }
  }

  useEffect(() => {
    refresh()
    return stopPolling
  }, [])

  const startPolling = () => {
    stopPolling()
    pollRef.current = setInterval(refresh, POLL_INTERVAL_MS)
  }

  const handleBind = async () => {
    const token = getStoredToken()
    if (!token) return
    setLoading(true)
    const result = await bindVm(token)
    setLoading(false)
    setVmStatus(result)
    if (result.status === 'launching') {
      startPolling()
    }
  }

  if (vmStatus?.status === 'ready') {
    return (
      <div className="auth-screen">
        <div className="auth-form">
          <h1>云主机已就绪</h1>
          <button type="button" onClick={onReady}>进入工作区</button>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-screen">
      <div className="auth-form">
        <h1>绑定云主机</h1>
        {vmStatus?.status === 'launching' && <div>环境准备中，预计 1~3 分钟...</div>}
        {vmStatus?.status === 'error' && <div className="auth-error">{vmStatus.error_message}</div>}
        {(!vmStatus || vmStatus.status === 'none' || vmStatus.status === 'error') && (
          <button type="button" disabled={loading} onClick={handleBind}>
            {loading ? '处理中...' : '创建云主机'}
          </button>
        )}
        {vmStatus?.status === 'stopped' && (
          <button type="button" disabled={loading} onClick={handleBind}>
            {loading ? '处理中...' : '启动云主机'}
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`
Expected: `BindNodePage.test.tsx passed` printed, exit code 0

Then run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new type errors introduced by `BindNodePage.tsx` (pre-existing unrelated errors in `components/`/`@/lib/utils` are expected and not your concern here).

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/BindNodePage.tsx opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx
git commit -m "feat: add BindNodePage component for per-user SkyPilot VM binding"
```

---

### Task 7: `Root.tsx` three-state gate (`LoginScreen` → `BindNodePage` → `App`)

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/auth/Root.tsx`
- Test: `opc/plugins/office_ui/frontend_src/auth/Root.test.tsx` (new — first test for this file)

**Interfaces:**
- Consumes: `getStoredToken` (`../lib/auth`, existing), `getVmStatus` (`../lib/vm`, Task 5), `BindNodePage` (Task 6).
- Produces: `Root()` now renders `LoginScreen` (no token) → `BindNodePage` (token but VM not `ready`) → `App` (VM `ready`).

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`:

```ts
// Source-text regex test — matches the LoginScreen.test.tsx convention.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'Root.tsx'), 'utf-8')

assert.match(source, /<LoginScreen/, 'Root must render LoginScreen when unauthenticated')
assert.match(source, /<BindNodePage/, 'Root must render BindNodePage when authenticated but VM is not ready')
assert.match(source, /<App\s*\/>/, 'Root must render App once the VM is ready')
assert.match(source, /getVmStatus\(/, "Root must check the caller's VM status")

console.log('Root.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`
Expected: FAIL on the `<BindNodePage` assertion (current `Root.tsx` only has `LoginScreen`/`App`)

- [ ] **Step 3: Write the implementation**

Replace the full contents of `opc/plugins/office_ui/frontend_src/auth/Root.tsx`:

```tsx
import { useEffect, useState } from 'react'
import App from '../App'
import { LoginScreen } from './LoginScreen'
import { BindNodePage } from './BindNodePage'
import { getStoredToken } from '../lib/auth'
import { getVmStatus } from '../lib/vm'

export default function Root() {
  const [authenticated, setAuthenticated] = useState<boolean>(getStoredToken() !== null)
  const [vmReady, setVmReady] = useState<boolean>(false)

  useEffect(() => {
    if (!authenticated) return
    const token = getStoredToken()
    if (!token) return
    getVmStatus(token).then((result) => {
      if (result.status === 'ready') setVmReady(true)
    })
  }, [authenticated])

  if (!authenticated) {
    return <LoginScreen onAuthenticated={() => setAuthenticated(true)} />
  }
  if (!vmReady) {
    return <BindNodePage onReady={() => setVmReady(true)} />
  }
  return <App />
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`
Expected: `Root.test.tsx passed` printed, exit code 0

Then run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new type errors introduced by this change.

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/Root.tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx
git commit -m "feat: gate workspace entry on per-user SkyPilot VM being ready"
```

---

### Task 8: Full-stack + real-AWS end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend and frontend test suites**

Run: `python -m pytest opc/plugins/office_ui/tests/ -q`
Expected: PASS, zero regressions from Tasks 1-4.

Run: `cd opc/plugins/office_ui/frontend_src && npx tsx --test lib/vm.test.ts auth/BindNodePage.test.tsx auth/Root.test.tsx auth/LoginScreen.test.tsx App.test.tsx`
Expected: PASS.

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in files touched by this plan.

- [ ] **Step 2: Build and start the real server**

```bash
cd opc/plugins/office_ui/frontend_src && npm install && npm run build
cd /Users/laiweichao/Documents/OpenOPC-main && opc ui
```

Expected: server starts at `http://localhost:8765` without errors.

- [ ] **Step 3: Confirm the SkyPilot AWS credentials are usable from this machine**

```bash
sky check aws
```

Expected: reports AWS enabled (this is a pre-flight check — if it fails, stop here and fix cloud credentials before continuing; Task 2's `TenantVmService` will otherwise reliably produce `status="error"`, which is a correct but unhelpful place to first discover a missing/misconfigured AWS credential).

- [ ] **Step 4: Register, bind, and confirm the VM comes up with Claude Code CLI installed**

In a second terminal, seed an invite code:

```bash
opc user create-invite DEMOCODE1
```

Open `http://localhost:8765` in a browser. Register with username `demo`, invite code `DEMOCODE1`.

Expected: after registering, the **绑定云主机** page renders (not the office app) — confirms `Root.tsx`'s new gate correctly blocks on `vmReady=false` for a freshly-registered account.

Click "创建云主机".

Expected: page shows "环境准备中，预计 1~3 分钟..." and polls every 5s. Wait for it to resolve (real `sky launch` — this genuinely takes 1-3+ minutes).

Expected outcome A (success): page shows "云主机已就绪" with a "进入工作区" button; clicking it renders the normal office UI.

Expected outcome B (if it errors): the page shows the `error_message` from the failed `sky launch` or the failed `claude --version` verification, with a "创建云主机" button to retry — confirms the error path surfaces something actionable rather than hanging silently.

- [ ] **Step 5: Confirm the VM is real and has the CLI installed, from the control host**

```bash
sky status
```

Expected: shows a cluster named `opc-tenant-<first 12 chars of the registered user's user_id>` with status `UP`.

```bash
sky exec opc-tenant-<cluster suffix> "claude --version"
```

Expected: prints a version string, confirming the `setup:` step in `tenant_vm.yaml` actually installed the CLI (this is the same command `TenantVmService._verify_and_finalize` already ran automatically — this step is a human double-check, not new functionality).

- [ ] **Step 6: Tear down the real cloud resource**

```bash
sky down opc-tenant-<cluster suffix> -y
```

Expected: cluster terminates — this step exists so the manual verification run doesn't leave a billable AWS instance running after this task is marked done.
