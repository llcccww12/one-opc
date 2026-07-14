# VM 工作区远程文件浏览器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a logged-in user browse, download, and delete files that Claude Code produced in their own SkyPilot VM's workspace, from the browser.

**Architecture:** Extends `WorkerConnectionRegistry` (sub-project 2) with a generic `request_id`-keyed request/response method (distinct from `dispatch_run_task`'s `task_id`-keyed one, per the spec's explicit choice to avoid conflating the two). `WorkerRuntime` (sub-project 2) gains `list_dir`/`read_file`/`delete_file` handlers, all funneled through one path-safety function that rejects any path escaping the project workspace root. The control plane exposes two new WS types (`list_workspace_files`/`delete_workspace_file`) and one new REST endpoint (`GET /api/vm/files/download`, since file content doesn't belong in a JSON WS message), all resolving "which worker to ask" via the existing `project_owners` ownership mechanism. The frontend adds a "文件" tab to the existing `ContextPanel`.

**Tech Stack:** Python 3.10+, aiohttp (existing). React 19 + TypeScript, zero test framework (`tsx` + `node:assert/strict`).

## Global Constraints

- **Hard ordering dependency: sub-project 2 (`opc worker` runtime mode) must be fully implemented before this plan starts.** Every task here modifies files sub-project 2 creates (`opc/layer3_agent/worker_registry.py`, `opc/layer3_agent/worker_runtime.py`) — this plan's diffs are written against the exact content specified in `docs/superpowers/plans/2026-07-14-opc-worker-runtime-mode-plan.md`. Confirm those files exist with that shape before starting; if they've since diverged, adapt the diffs accordingly rather than blindly applying them.
- Scope is **read + delete + download only** — no in-browser editing/write-back, no upload from browser to VM, no chunked/resumable transfer for large files. These are explicit non-goals from the design spec.
- All three new worker-side file operations (`list_dir`, `read_file`, `delete_file`) MUST go through the single `_resolve_safe_path` function — no operation touches the filesystem with a caller-supplied path that hasn't passed through it first. This is the new feature's own security floor; it must not repeat the pre-existing, out-of-scope `opc/layer4_tools/file_ops.py` path-validation gap.
- **Implementation simplification from the design spec:** the spec describes a tree view with double-click expand/collapse. This plan implements a simpler breadcrumb-style navigator instead (click a directory to descend into it, "上一级" button to go back) — functionally equivalent (see/download/delete everything, no dead ends), less UI code, and avoids needing to fetch/cache multiple directory levels at once just to render expand/collapse state. If a true tree view is wanted later, `FilesPanel` can be swapped without touching the backend protocol at all (it already returns flat per-directory listings, which is exactly what a tree view would also consume node-by-node).
- The REST download endpoint accepts the session token via **either** an `Authorization: Bearer` header **or** a `?token=` query parameter — the query-param form exists so a plain `<a href>` browser download link works (browsers cannot attach custom headers to a top-level navigation/download), matching how download links commonly work elsewhere on the web. Both forms resolve through the same `UserStore.get_user_id_for_token`.
- "Who owns this project" (and therefore which worker connection to route file requests to) is resolved via the pre-existing `UserStore.get_project_owner(project_id)` (already used by `ExternalAgentBroker`'s `owner_resolver` in sub-project 2) — do not introduce a second ownership-resolution mechanism.
- Backend tests run with `python -m pytest tests/<file>.py -q` (for `layer3_agent` files) or `opc/plugins/office_ui/tests/<file>.py -q` (for `office_ui` plugin files) — matches existing directory conventions.
- Any new WS request type must be added to `docs/FRONTEND_BACKEND_MAP.md` in the same task that introduces it.

---

### Task 1: Extend `WorkerConnectionRegistry` with generic `request_id`-keyed dispatch

**Files:**
- Modify: `opc/layer3_agent/worker_registry.py`
- Modify: `tests/test_worker_registry.py`

**Interfaces:**
- Produces: `WorkerConnectionRegistry.dispatch_request(user_id: str, request_id: str, message: dict, timeout_seconds: float) -> dict | None` — sends `message` to the connected worker and returns whatever raw dict it replies with (matched by `request_id`, not `task_id`); returns `None` if not connected or on timeout. `handle_worker_message` now checks for `request_id` first (routes to this new mechanism) before falling through to the existing `task_id`-based `run_task`/`progress`/`task_complete` routing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker_registry.py` (add to the existing `WorkerConnectionRegistryTests` class):

```python
    async def test_dispatch_request_returns_none_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        result = await registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=1)
        self.assertIsNone(result)

    async def test_dispatch_request_sends_message_and_returns_raw_response(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_request("user-1", "req-1", {"type": "list_dir", "request_id": "req-1"}, timeout_seconds=5)
        )
        await asyncio.sleep(0)
        await registry.handle_worker_message({"type": "dir_listing", "request_id": "req-1", "entries": []})
        response = await dispatch_task

        connection.send_json.assert_awaited_once_with({"type": "list_dir", "request_id": "req-1"})
        self.assertEqual(response, {"type": "dir_listing", "request_id": "req-1", "entries": []})

    async def test_dispatch_request_times_out_when_no_response(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        result = await registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=0.05)
        self.assertIsNone(result)

    async def test_dispatch_request_and_dispatch_run_task_do_not_interfere(self) -> None:
        """request_id-keyed and task_id-keyed multiplexing must be independent —
        a run_task in flight must not be resolved by a request_id-keyed reply
        and vice versa."""
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())

        task_dispatch = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=5)
        )
        request_dispatch = asyncio.ensure_future(
            registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=5)
        )
        await asyncio.sleep(0)

        await registry.handle_worker_message({"type": "dir_listing", "request_id": "req-1", "entries": []})
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "", "stderr": "", "resume_session_id": None,
        })

        request_result = await request_dispatch
        task_result = await task_dispatch
        self.assertEqual(request_result, {"type": "dir_listing", "request_id": "req-1", "entries": []})
        self.assertEqual(task_result.returncode, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_worker_registry.py -v`
Expected: FAIL with `AttributeError: 'WorkerConnectionRegistry' object has no attribute 'dispatch_request'`

- [ ] **Step 3: Write the implementation**

In `opc/layer3_agent/worker_registry.py`, add a new dict to `__init__` (right after `self._pending: dict[str, _PendingRequest] = {}`):

```python
        self._pending_requests: dict[str, asyncio.Future] = {}
```

Add the new method right after `dispatch_run_task`:

```python
    async def dispatch_request(
        self, user_id: str, request_id: str, message: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any] | None:
        """Generic request/response over a worker connection, keyed by
        request_id — distinct from dispatch_run_task's task_id-keyed
        multiplexing, since a connection can have a run_task and a file-browse
        request in flight at once and the two must not resolve each other."""
        connection = self._connections.get(user_id)
        if connection is None:
            return None

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future
        try:
            await connection.send_json(message)
            try:
                return await asyncio.wait_for(future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return None
        finally:
            self._pending_requests.pop(request_id, None)
```

Change `handle_worker_message` to check `request_id` first, before its existing `task_id` logic:

```python
    async def handle_worker_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("request_id")
        if request_id is not None:
            future = self._pending_requests.get(request_id)
            if future is not None and not future.done():
                future.set_result(message)
            return

        task_id = message.get("task_id")
        pending = self._pending.get(task_id) if task_id else None
        if pending is None:
            return

        msg_type = message.get("type")
        if msg_type == "progress" and pending.on_progress is not None:
            await pending.on_progress(str(message.get("text") or ""))
        elif msg_type == "task_complete":
            if not pending.future.done():
                pending.future.set_result(
                    WorkerTaskOutcome(
                        returncode=int(message.get("returncode", 1)),
                        stdout=str(message.get("stdout") or ""),
                        stderr=str(message.get("stderr") or ""),
                        resume_session_id=message.get("resume_session_id"),
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_registry.py -v`
Expected: PASS (all tests, including the pre-existing `run_task`-focused ones)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/worker_registry.py tests/test_worker_registry.py
git commit -m "feat: add request_id-keyed generic dispatch to WorkerConnectionRegistry"
```

---

### Task 2: Worker-side path-safe file operations

**Files:**
- Modify: `opc/layer3_agent/worker_runtime.py`
- Modify: `tests/test_worker_runtime.py`

**Interfaces:**
- Produces: module-level `_resolve_safe_path(workspace_root: Path, relative_path: str) -> Path` (raises `ValueError` on any path escaping `workspace_root`); `WorkerRuntime._handle_list_dir`/`_handle_read_file`/`_handle_delete_file`, all dispatched from `_handle_message` for `"list_dir"`/`"read_file"`/`"delete_file"` message types.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker_runtime.py`:

```python
import base64


class WorkerRuntimeFileOpsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.workspace_root = Path(tempfile.mkdtemp())
        self.runtime = WorkerRuntime("http://localhost:8765", "tok", self.workspace_root)
        self.project_dir = self.workspace_root / "demo"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "notes.txt").write_text("hello world")
        (self.project_dir / "subdir").mkdir()

    async def test_list_dir_returns_entries(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_list_dir(ws, {"request_id": "r1", "project_id": "demo", "path": ""})
        sent = ws.send_json.await_args.args[0]
        names = {e["name"] for e in sent["entries"]}
        self.assertEqual(names, {"notes.txt", "subdir"})

    async def test_list_dir_rejects_path_traversal(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_list_dir(ws, {"request_id": "r1", "project_id": "demo", "path": "../../etc"})
        sent = ws.send_json.await_args.args[0]
        self.assertEqual(sent.get("error"), "invalid_path")

    async def test_read_file_returns_base64_content(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_read_file(ws, {"request_id": "r1", "project_id": "demo", "path": "notes.txt"})
        sent = ws.send_json.await_args.args[0]
        decoded = base64.b64decode(sent["content_base64"]).decode("utf-8")
        self.assertEqual(decoded, "hello world")

    async def test_read_file_rejects_path_traversal(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_read_file(ws, {"request_id": "r1", "project_id": "demo", "path": "../../../etc/passwd"})
        sent = ws.send_json.await_args.args[0]
        self.assertEqual(sent.get("error"), "invalid_path")

    async def test_read_file_missing_reports_not_found(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_read_file(ws, {"request_id": "r1", "project_id": "demo", "path": "missing.txt"})
        sent = ws.send_json.await_args.args[0]
        self.assertEqual(sent.get("error"), "not_found")

    async def test_delete_file_removes_file(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_delete_file(ws, {"request_id": "r1", "project_id": "demo", "path": "notes.txt"})
        sent = ws.send_json.await_args.args[0]
        self.assertTrue(sent["ok"])
        self.assertFalse((self.project_dir / "notes.txt").exists())

    async def test_delete_dir_removes_recursively(self) -> None:
        (self.project_dir / "subdir" / "nested.txt").write_text("x")
        ws = AsyncMock()
        await self.runtime._handle_delete_file(ws, {"request_id": "r1", "project_id": "demo", "path": "subdir"})
        sent = ws.send_json.await_args.args[0]
        self.assertTrue(sent["ok"])
        self.assertFalse((self.project_dir / "subdir").exists())

    async def test_delete_file_rejects_path_traversal(self) -> None:
        ws = AsyncMock()
        await self.runtime._handle_delete_file(ws, {"request_id": "r1", "project_id": "demo", "path": "../../etc/passwd"})
        sent = ws.send_json.await_args.args[0]
        self.assertFalse(sent["ok"])
        self.assertEqual(sent["error"], "invalid_path")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_worker_runtime.py -v -k FileOps`
Expected: FAIL with `AttributeError: 'WorkerRuntime' object has no attribute '_handle_list_dir'`

- [ ] **Step 3: Write the implementation**

In `opc/layer3_agent/worker_runtime.py`, add imports at the top (alongside the existing `import asyncio`/`import json`):

```python
import base64
import shutil
```

Add the module-level path-safety function, right after the `_RECONNECT_DELAY_SECONDS` constant:

```python
def _resolve_safe_path(workspace_root: Path, relative_path: str) -> Path:
    """Resolve relative_path under workspace_root, rejecting any path that
    would escape it (path traversal, absolute paths, symlinks pointing
    outward). Every worker-side file operation MUST go through this."""
    candidate = (workspace_root / relative_path).resolve()
    root = workspace_root.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path escapes workspace root")
    return candidate
```

Change `_handle_message` to dispatch the three new message types (add these `elif` branches after the existing `cancel_task` one):

```python
        elif msg_type == "list_dir":
            await self._handle_list_dir(ws, data)
        elif msg_type == "read_file":
            await self._handle_read_file(ws, data)
        elif msg_type == "delete_file":
            await self._handle_delete_file(ws, data)
```

Add the three handlers as new methods on `WorkerRuntime` (place them after `_handle_cancel_task`):

```python
    async def _handle_list_dir(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        workspace_path = self._workspace_root / str(data.get("project_id") or "default")
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": "invalid_path"})
            return

        if not target.exists() or not target.is_dir():
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": "not_found"})
            return

        entries = []
        for child in sorted(target.iterdir()):
            stat_result = child.stat()
            entries.append({
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": stat_result.st_size,
                "mtime": stat_result.st_mtime,
            })
        await ws.send_json({"type": "dir_listing", "request_id": request_id, "entries": entries})

    async def _handle_read_file(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        workspace_path = self._workspace_root / str(data.get("project_id") or "default")
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": "invalid_path"})
            return

        if not target.exists() or not target.is_file():
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": "not_found"})
            return

        content_bytes = target.read_bytes()
        await ws.send_json({
            "type": "file_content",
            "request_id": request_id,
            "content_base64": base64.b64encode(content_bytes).decode("ascii"),
        })

    async def _handle_delete_file(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        workspace_path = self._workspace_root / str(data.get("project_id") or "default")
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": "invalid_path"})
            return

        if not target.exists():
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": "not_found"})
            return

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": str(exc)})
            return

        await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_runtime.py -v`
Expected: PASS (all tests, including pre-existing `run_task`/`cancel_task` ones from sub-project 2)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/worker_runtime.py tests/test_worker_runtime.py
git commit -m "feat: add path-safe list_dir/read_file/delete_file handlers to WorkerRuntime"
```

---

### Task 3: Control-plane WS handlers `list_workspace_files` / `delete_workspace_file`

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Modify: `docs/FRONTEND_BACKEND_MAP.md`
- Test: `opc/plugins/office_ui/tests/test_workspace_files_ws.py`

**Interfaces:**
- Consumes: `WorkerConnectionRegistry.dispatch_request`/`is_connected` (Task 1), `UserStore.get_project_owner` (existing).
- Produces: WS request types `list_workspace_files` (`{"project_id": ..., "path": ...}`) and `delete_workspace_file` (`{"project_id": ..., "path": ...}`), both replying with `{"type": ..., "payload": {"ok": ..., ...}}`.

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/tests/test_workspace_files_ws.py`:

```python
"""WS-level tests for list_workspace_files / delete_workspace_file."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler(worker_registry, user_store) -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.engine.worker_registry = worker_registry
    handler._user_store = user_store
    handler._safe_send_json = AsyncMock()
    return handler


class WorkspaceFilesWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_workspace_files_reports_error_when_no_owner(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = None
        handler = _make_handler(MagicMock(), user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "worker_not_connected")

    async def test_list_workspace_files_reports_error_when_worker_not_connected(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = False
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "worker_not_connected")

    async def test_list_workspace_files_returns_entries_on_success(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "dir_listing", "entries": [{"name": "a.txt"}]})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["entries"], [{"name": "a.txt"}])

    async def test_list_workspace_files_returns_error_when_dispatch_times_out(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value=None)
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "timeout")

    async def test_delete_workspace_file_returns_ok_on_success(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "delete_result", "ok": True})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_delete_workspace_file(ws, {"project_id": "demo", "path": "notes.txt"})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])

    async def test_delete_workspace_file_forwards_worker_error(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "delete_result", "ok": False, "error": "not_found"})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_delete_workspace_file(ws, {"project_id": "demo", "path": "notes.txt"})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_workspace_files_ws.py -v`
Expected: FAIL with `AttributeError: 'WSHandler' object has no attribute '_handle_list_workspace_files'`

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/ws_handler.py`, add `import secrets` near the top if not already present (check the existing import block first — `secrets` is commonly already imported elsewhere in this large file; only add if genuinely missing).

Add the two handlers near `_handle_list_nodes` (place them right after it):

```python
    async def _handle_list_workspace_files(self, ws: Any, data: dict) -> None:
        project_id = str(data.get("project_id") or "")
        owner_user_id = await self._user_store.get_project_owner(project_id) if self._user_store else None
        if not owner_user_id or not self.engine.worker_registry.is_connected(owner_user_id):
            await self._safe_send_json(
                ws, {"type": "list_workspace_files", "payload": {"ok": False, "error": "worker_not_connected"}}
            )
            return

        request_id = secrets.token_hex(8)
        response = await self.engine.worker_registry.dispatch_request(
            owner_user_id,
            request_id,
            {"type": "list_dir", "request_id": request_id, "project_id": project_id, "path": str(data.get("path") or "")},
            timeout_seconds=30,
        )
        if response is None:
            await self._safe_send_json(
                ws, {"type": "list_workspace_files", "payload": {"ok": False, "error": "timeout"}}
            )
            return
        if response.get("error"):
            await self._safe_send_json(
                ws, {"type": "list_workspace_files", "payload": {"ok": False, "error": response["error"]}}
            )
            return
        await self._safe_send_json(
            ws, {"type": "list_workspace_files", "payload": {"ok": True, "entries": response.get("entries", [])}}
        )

    async def _handle_delete_workspace_file(self, ws: Any, data: dict) -> None:
        project_id = str(data.get("project_id") or "")
        owner_user_id = await self._user_store.get_project_owner(project_id) if self._user_store else None
        if not owner_user_id or not self.engine.worker_registry.is_connected(owner_user_id):
            await self._safe_send_json(
                ws, {"type": "delete_workspace_file", "payload": {"ok": False, "error": "worker_not_connected"}}
            )
            return

        request_id = secrets.token_hex(8)
        response = await self.engine.worker_registry.dispatch_request(
            owner_user_id,
            request_id,
            {"type": "delete_file", "request_id": request_id, "project_id": project_id, "path": str(data.get("path") or "")},
            timeout_seconds=30,
        )
        if response is None:
            await self._safe_send_json(
                ws, {"type": "delete_workspace_file", "payload": {"ok": False, "error": "timeout"}}
            )
            return
        await self._safe_send_json(
            ws,
            {"type": "delete_workspace_file", "payload": {"ok": bool(response.get("ok")), "error": response.get("error")}},
        )
```

Register both in the `_HANDLERS` dict, right after the existing `"list_nodes": _handle_list_nodes,` entry:

```python
        "list_workspace_files":   _handle_list_workspace_files,
        "delete_workspace_file":  _handle_delete_workspace_file,
```

Add both to the existing `_OWNERSHIP_CHECKED_MESSAGE_TYPES` frozenset (near the top of the file, before `class WSHandler:`) — this makes the existing generic project-ownership check in `_route_message` reject cross-user `project_id` values before either handler above even runs:

```python
    "list_workspace_files",
    "delete_workspace_file",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_workspace_files_ws.py -v`
Expected: PASS (6 tests)

Run the broader regression suite to confirm the `_OWNERSHIP_CHECKED_MESSAGE_TYPES` addition and new `_HANDLERS` entries didn't break anything:

Run: `python -m pytest opc/plugins/office_ui/tests/ -q`
Expected: PASS

- [ ] **Step 5: Document in FRONTEND_BACKEND_MAP.md**

Add a new section after the "Nodes（SkyPilot 集群状态，只读）" section added by an earlier plan:

```markdown
## 二十一、VM 工作区文件浏览器

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | WS 响应类型 |
|------|----------|-------------|--------------|-------------|
| 列目录 | FilesPanel | `list_workspace_files` | `_handle_list_workspace_files` | 同类型消息 |
| 删除文件/文件夹 | FilesPanel | `delete_workspace_file` | `_handle_delete_workspace_file` | 同类型消息 |
| 下载文件 | FilesPanel | `GET /api/vm/files/download`（REST，不走 WS） | `make_file_download_handler` | 文件流 |
```

- [ ] **Step 6: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py docs/FRONTEND_BACKEND_MAP.md opc/plugins/office_ui/tests/test_workspace_files_ws.py
git commit -m "feat: wire list_workspace_files/delete_workspace_file WS request types"
```

---

### Task 4: REST download endpoint `GET /api/vm/files/download`

**Files:**
- Create: `opc/plugins/office_ui/file_download_routes.py`
- Modify: `opc/plugins/office_ui/server.py`
- Test: `opc/plugins/office_ui/tests/test_file_download_routes.py`

**Interfaces:**
- Consumes: `UserStore.get_user_id_for_token`/`get_project_owner` (existing), `WorkerConnectionRegistry.is_connected`/`dispatch_request` (Task 1).
- Produces: `make_file_download_handler(user_store: UserStore, worker_registry: WorkerConnectionRegistry) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]`, mounted at `GET /api/vm/files/download?project_id=...&path=...`, auth via `Authorization: Bearer <token>` header **or** `?token=<token>` query param.

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/tests/test_file_download_routes.py`:

```python
"""Tests for GET /api/vm/files/download."""

from __future__ import annotations

import asyncio
import base64
import unittest
from unittest.mock import AsyncMock

import aiosqlite
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.file_download_routes import make_file_download_handler
from opc.plugins.office_ui.user_store import UserStore


class FileDownloadRouteTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.db = await aiosqlite.connect(":memory:")
        self.user_store = UserStore(self.db)
        await self.user_store.initialize()
        await self.user_store.create_invite_code("INVITE1")
        self.user_id, _ = await self.user_store.register("alice", "INVITE1")
        self.token = await self.user_store.create_session(self.user_id)
        await self.user_store.record_project_owner("demo", self.user_id)

        self.registry = WorkerConnectionRegistry()
        app = web.Application()
        app.router.add_get("/api/vm/files/download", make_file_download_handler(self.user_store, self.registry))
        return app

    async def tearDownAsync(self) -> None:
        await self.db.close()
        await super().tearDownAsync()

    async def test_download_without_token_returns_401(self) -> None:
        resp = await self.client.get("/api/vm/files/download?project_id=demo&path=notes.txt")
        self.assertEqual(resp.status, 401)

    async def test_download_for_project_owned_by_someone_else_returns_403(self) -> None:
        await self.user_store.create_invite_code("INVITE2")
        other_user_id, _ = await self.user_store.register("bob", "INVITE2")
        other_token = await self.user_store.create_session(other_user_id)
        resp = await self.client.get(
            "/api/vm/files/download?project_id=demo&path=notes.txt",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        self.assertEqual(resp.status, 403)

    async def test_download_when_worker_not_connected_returns_409(self) -> None:
        resp = await self.client.get(
            "/api/vm/files/download?project_id=demo&path=notes.txt",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status, 409)

    async def test_download_accepts_token_via_query_param(self) -> None:
        resp = await self.client.get(f"/api/vm/files/download?project_id=demo&path=notes.txt&token={self.token}")
        self.assertEqual(resp.status, 409)  # auth succeeded; 409 is the next real check (worker not connected)

    async def test_download_streams_file_content(self) -> None:
        connection = AsyncMock()
        self.registry.register(self.user_id, connection)

        async def _respond() -> None:
            await asyncio.sleep(0.01)
            sent_message = connection.send_json.await_args.args[0]
            await self.registry.handle_worker_message({
                "type": "file_content",
                "request_id": sent_message["request_id"],
                "content_base64": base64.b64encode(b"hello world").decode("ascii"),
            })

        asyncio.ensure_future(_respond())
        resp = await self.client.get(
            "/api/vm/files/download?project_id=demo&path=notes.txt",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.read()
        self.assertEqual(body, b"hello world")
        self.assertIn("notes.txt", resp.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_file_download_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.file_download_routes'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/file_download_routes.py`:

```python
"""HTTP handler for downloading a file from a user's VM workspace
(GET /api/vm/files/download?project_id=...&path=...).

Uses REST rather than a WS request type because file content doesn't belong
in a JSON WS message body — the response here streams a plain HTTP body.
"""

from __future__ import annotations

import base64
import secrets

import aiohttp.web

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.user_store import UserStore

_DOWNLOAD_TIMEOUT_SECONDS = 30


def make_file_download_handler(user_store: UserStore, worker_registry: WorkerConnectionRegistry):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.StreamResponse:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):].strip()
        else:
            token = str(request.query.get("token") or "")

        requesting_user_id = await user_store.get_user_id_for_token(token) if token else None
        if requesting_user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        project_id = str(request.query.get("project_id") or "")
        path = str(request.query.get("path") or "")
        owner_user_id = await user_store.get_project_owner(project_id)
        if not owner_user_id or owner_user_id != requesting_user_id:
            return aiohttp.web.json_response({"ok": False, "error": "forbidden"}, status=403)

        if not worker_registry.is_connected(owner_user_id):
            return aiohttp.web.json_response({"ok": False, "error": "worker_not_connected"}, status=409)

        request_id = secrets.token_hex(8)
        response = await worker_registry.dispatch_request(
            owner_user_id,
            request_id,
            {"type": "read_file", "request_id": request_id, "project_id": project_id, "path": path},
            timeout_seconds=_DOWNLOAD_TIMEOUT_SECONDS,
        )
        if response is None or response.get("error"):
            error = (response or {}).get("error", "timeout")
            return aiohttp.web.json_response({"ok": False, "error": error}, status=404)

        content = base64.b64decode(response["content_base64"])
        filename = path.rsplit("/", 1)[-1] or "download"
        return aiohttp.web.Response(
            body=content,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return _handle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_file_download_routes.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire into `server.py`**

Add the import right after `from opc.plugins.office_ui.worker_ws import make_worker_ws_handler`:

```python
from opc.plugins.office_ui.file_download_routes import make_file_download_handler
```

In the "Routes" block, add the new endpoint right after the existing `/worker/ws` route:

```python
    app.router.add_get(
        "/api/vm/files/download", make_file_download_handler(user_store, engine.worker_registry)
    )
```

- [ ] **Step 6: Run the broader regression suite**

Run: `python -m pytest opc/plugins/office_ui/tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add opc/plugins/office_ui/file_download_routes.py opc/plugins/office_ui/server.py opc/plugins/office_ui/tests/test_file_download_routes.py
git commit -m "feat: add GET /api/vm/files/download REST endpoint"
```

---

### Task 5: Frontend "文件" tab in `ContextPanel`

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`
- Create: `opc/plugins/office_ui/frontend_src/workspace/FilesPanel.tsx`
- Create: `opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/workspace/ContextPanel.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx`

**Interfaces:**
- Produces: `VisualSocketClient.listWorkspaceFiles(projectId: string, path: string): void`, `.deleteWorkspaceFile(projectId: string, path: string): void`, plus `SocketHandlers.onListWorkspaceFiles?`/`onDeleteWorkspaceFile?`; `FilesPanel({ projectId, entries, currentPath, onNavigate, onRefresh, onDelete, downloadUrlFor }: FilesPanelProps)` — presentational, no direct `wsClient` dependency (matches the established `App.tsx`-owns-state convention).

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`:

```ts
// Source-text regex test — matches the LoginScreen.test.tsx convention for
// components that touch browser globals and can't be rendered under plain
// Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'FilesPanel.tsx'), 'utf-8')

assert.match(source, /onNavigate\(/, 'FilesPanel must call onNavigate to change directory')
assert.match(source, /onDelete\(/, 'FilesPanel must call onDelete to remove an entry')
assert.match(source, /downloadUrlFor\(/, 'FilesPanel must build a download URL per entry, not hardcode one')
assert.doesNotMatch(source, /VisualSocketClient/, 'FilesPanel must stay presentational — no direct wsClient dependency')

console.log('FilesPanel.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`
Expected: FAIL — `ENOENT: no such file or directory ... FilesPanel.tsx`

- [ ] **Step 3: Implement `wsClient.ts`**

Add to the `SocketHandlers` interface, right after the existing `onListNodes?` line:

```ts
  onListWorkspaceFiles?: (payload: { ok: boolean; entries?: Array<{ name: string; is_dir: boolean; size: number; mtime: number }>; error?: string }) => void
  onDeleteWorkspaceFile?: (payload: { ok: boolean; error?: string }) => void
```

Add the two send methods, right after `listNodes`:

```ts
  listWorkspaceFiles(projectId: string, path: string): void {
    this.send({ type: 'list_workspace_files', project_id: projectId, path })
  }

  deleteWorkspaceFile(projectId: string, path: string): void {
    this.send({ type: 'delete_workspace_file', project_id: projectId, path })
  }
```

Add the two dispatch cases, right after the `list_nodes` case:

```ts
      case 'list_workspace_files':
        this.handlers.onListWorkspaceFiles?.(parsed.payload as { ok: boolean; entries?: any[]; error?: string })
        break
      case 'delete_workspace_file':
        this.handlers.onDeleteWorkspaceFile?.(parsed.payload as { ok: boolean; error?: string })
        break
```

`list_workspace_files`/`delete_workspace_file` **are** project-scoped (they carry `project_id`) — add both to `PROJECT_SCOPED_MESSAGE_TYPES` alongside the other project-scoped entries.

- [ ] **Step 4: Implement `FilesPanel.tsx`**

Create `opc/plugins/office_ui/frontend_src/workspace/FilesPanel.tsx`:

```tsx
export interface WorkspaceFileEntry {
  name: string
  is_dir: boolean
  size: number
  mtime: number
}

interface FilesPanelProps {
  currentPath: string
  entries: WorkspaceFileEntry[] | null
  error: string | null
  onNavigate: (path: string) => void
  onRefresh: () => void
  onDelete: (name: string) => void
  downloadUrlFor: (name: string) => string
}

function parentPath(path: string): string {
  const idx = path.lastIndexOf('/')
  return idx === -1 ? '' : path.slice(0, idx)
}

export function FilesPanel({ currentPath, entries, error, onNavigate, onRefresh, onDelete, downloadUrlFor }: FilesPanelProps) {
  return (
    <div className="files-panel">
      <div className="files-toolbar">
        <button type="button" disabled={!currentPath} onClick={() => onNavigate(parentPath(currentPath))}>上一级</button>
        <span className="files-path">{currentPath || '/'}</span>
        <button type="button" onClick={onRefresh}>刷新</button>
      </div>
      {error && <div className="files-error">{error}</div>}
      {!entries || entries.length === 0 ? (
        <div className="files-empty">空目录</div>
      ) : (
        <ul className="files-list">
          {entries.map(entry => (
            <li key={entry.name} className="files-row">
              {entry.is_dir ? (
                <button
                  type="button"
                  className="files-name files-dir"
                  onClick={() => onNavigate(currentPath ? `${currentPath}/${entry.name}` : entry.name)}
                >
                  {entry.name}/
                </button>
              ) : (
                <a className="files-name" href={downloadUrlFor(entry.name)}>{entry.name}</a>
              )}
              <button type="button" className="files-delete" onClick={() => { if (window.confirm(`删除 ${entry.name}？`)) onDelete(entry.name) }}>删除</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`
Expected: `FilesPanel.test.tsx passed` printed, exit code 0

- [ ] **Step 6: Wire into `ContextPanel.tsx` and `App.tsx`**

In `opc/plugins/office_ui/frontend_src/workspace/ContextPanel.tsx`, extend the `panelTab` union (line 72-73) from `'chat' | 'agents' | 'info' | 'comms' | 'team'` to `'chat' | 'agents' | 'info' | 'comms' | 'team' | 'files'`, add a new tab button next to the existing `team` tab button (same `ctx-tab` pattern as the others), and add a rendering block `{panelTab === 'files' && <FilesPanel ... />}` alongside the existing `panelTab === 'team'` block — forward `filesEntries`/`filesError`/`filesCurrentPath`/`onFilesNavigate`/`onFilesRefresh`/`onFilesDelete`/`filesDownloadUrlFor` as new `ContextPanelProps` fields, following the exact same "new optional prop, forwarded straight through" pattern the other four tabs already use (read the existing prop list at the top of `ContextPanelProps` to match its ordering/style before adding).

In `opc/plugins/office_ui/frontend_src/App.tsx`, add state for the current directory/listing (next to the other per-feature state blocks, e.g. near `nodesData`):

```tsx
const [filesCurrentPath, setFilesCurrentPath] = useState('')
const [filesEntries, setFilesEntries] = useState<WorkspaceFileEntry[] | null>(null)
const [filesError, setFilesError] = useState<string | null>(null)
```

(Import `type { WorkspaceFileEntry }` from `./workspace/FilesPanel` alongside the other workspace-panel imports.)

Add handlers to the `VisualSocketClient` construction's handlers object literal, alongside `onListNodes`:

```tsx
      onListWorkspaceFiles: (payload) => {
        if (payload.ok) {
          setFilesEntries(payload.entries ?? [])
          setFilesError(null)
        } else {
          setFilesError(payload.error || 'Failed to list files')
        }
      },
      onDeleteWorkspaceFile: (payload) => {
        if (payload.ok) {
          clientRef.current?.listWorkspaceFiles(activeProjectId, filesCurrentPath)
        } else {
          setFilesError(payload.error || 'Delete failed')
        }
      },
```

(`activeProjectId` should already exist as the currently-active project id state in `App.tsx` — reuse it, do not introduce a second source of truth for "which project is open.")

Pass the new props into `<ContextPanel ... />`'s existing call site:

```tsx
        filesCurrentPath={filesCurrentPath}
        filesEntries={filesEntries}
        filesError={filesError}
        onFilesNavigate={(path) => { setFilesCurrentPath(path); clientRef.current?.listWorkspaceFiles(activeProjectId, path) }}
        onFilesRefresh={() => clientRef.current?.listWorkspaceFiles(activeProjectId, filesCurrentPath)}
        onFilesDelete={(name) => clientRef.current?.deleteWorkspaceFile(activeProjectId, filesCurrentPath ? `${filesCurrentPath}/${name}` : name)}
        filesDownloadUrlFor={(name) => {
          const fullPath = filesCurrentPath ? `${filesCurrentPath}/${name}` : name
          const token = getStoredToken() ?? ''
          return `/api/vm/files/download?project_id=${encodeURIComponent(activeProjectId)}&path=${encodeURIComponent(fullPath)}&token=${encodeURIComponent(token)}`
        }}
```

(`getStoredToken` from `./lib/auth` — it should already be imported in `App.tsx` from earlier work; if not, add `import { getStoredToken } from './lib/auth'`.)

- [ ] **Step 7: Run typecheck and existing regression tests**

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in `ContextPanel.tsx`/`App.tsx`/`FilesPanel.tsx`/`wsClient.ts`.

Run: `npx tsx --test lib/wsClient.test.ts workspace/FilesPanel.test.tsx App.test.tsx`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/lib/wsClient.ts opc/plugins/office_ui/frontend_src/workspace/FilesPanel.tsx opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx opc/plugins/office_ui/frontend_src/workspace/ContextPanel.tsx opc/plugins/office_ui/frontend_src/App.tsx
git commit -m "feat: add read-only VM workspace file browser (文件 tab) to ContextPanel"
```

---

### Task 6: Full-stack + real-VM end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend and frontend test suites**

Run: `python -m pytest tests/ opc/plugins/office_ui/tests/ -q`
Expected: PASS, zero regressions from Tasks 1-4.

Run: `cd opc/plugins/office_ui/frontend_src && npx tsx --test lib/wsClient.test.ts workspace/FilesPanel.test.tsx App.test.tsx`
Expected: PASS.

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in files touched by this plan.

- [ ] **Step 2: Real end-to-end run**

Using a real VM with a connected worker (reuse sub-project 2's end-to-end setup — a worker must be connected for this feature to do anything):

1. Run a Task Mode chat message that causes Claude Code to create a file in the project workspace (e.g. ask it to write a short text file).
2. Open the "文件" tab in `ContextPanel`. Confirm the created file appears in the listing.
3. Click the file to download it. Confirm the downloaded content matches what was written on the VM (check via `sky exec <cluster> "cat ~/opc_workspace/<project_id>/<file>"`).
4. Create a subdirectory on the VM (`sky exec <cluster> "mkdir -p ~/opc_workspace/<project_id>/subdir"`), confirm it's navigable via "上一级"/directory-click in the panel.
5. Delete a file via the panel's "删除" button. Confirm it's actually gone on the VM (`sky exec <cluster> "ls ~/opc_workspace/<project_id>/"`).
6. As a second user (different account, no access to this project), attempt to call `list_workspace_files`/`GET /api/vm/files/download` with the first user's `project_id` directly (e.g. via browser devtools console) — confirm both are rejected (`project_access_denied` for the WS type via the existing ownership check; `403 forbidden` for the download route).

- [ ] **Step 3: Report residual known limitations**

Confirm these are true and acceptable (matching the design spec's own non-goals):

- No in-browser file editing/write-back — this round is read + delete + download only.
- No upload from browser to VM.
- No chunked/resumable download for very large files — the entire file content is base64-encoded and sent as one WS message between the worker and control plane before being streamed to the browser; this is a known scaling limit if agents ever produce very large artifacts, deferred until it's a real problem.
