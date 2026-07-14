# `opc worker` 运行模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route claude_code external-agent tasks to a connected user's own SkyPilot VM instead of running them on the control plane — the VM runs a new `opc worker` process that reuses the existing `ClaudeCodeAdapter` locally, streams progress back over an outbound WebSocket, and supports multi-turn `--resume` continuity.

**Architecture:** A new `WorkerConnectionRegistry` (owned by `OPCEngine`) tracks which user's worker is currently connected and multiplexes `run_task`/`progress`/`task_complete`/`cancel_task` messages by `task_id`. A new `/worker/ws` endpoint (auth via the `tenant_vms.auth_token` from sub-project 1) registers incoming VM connections into it. `ExternalAgentBroker.run()` gets one new branch inserted before its existing mode dispatch: if the task's project owner has a connected worker, route through a new `_run_via_worker()` method instead of the existing local-subprocess path — the existing local path (`_run_monitored_process`, `_run_interactive`) is **not modified**. `opc worker start` (new CLI command, runs on the VM) connects outbound, and on `run_task` spawns `claude` locally via `ClaudeCodeAdapter.start_process()` using the exact argv the control plane already built (including any `--resume <id>` flag) — file/tool operations happen on the VM's own disk, no sync needed.

**Tech Stack:** Python 3.10+, aiohttp (existing, `ClientSession.ws_connect` for the outbound worker connection — new usage of an already-available library), asyncio.

## Global Constraints

- **Deviation from the design spec:** the spec (`docs/superpowers/specs/2026-07-14-opc-worker-runtime-mode-design.md`) describes extracting `_run_monitored_process`'s spawn/stream/wait logic into a shared `process_runner.py` used by both the local path and the worker path. Investigation into the actual method (`opc/layer3_agent/external_broker.py:577-1268`, ~692 lines) found this extraction is not safely separable: nearly every line inside its `_consume` inner loop closes over broker-only state (`self.store`, `task`, approval prompts, trace logging, runtime-failure reaction) — only ~30-40 lines (spawn call, raw `proc.wait()`, `extract_resume_session_id`) are genuinely generic, and lifting `_consume` wholesale would require redesigning its per-line branching around callback-returned signals instead of closure mutation. Given that risk against an MVP goal, this plan takes a smaller, safer path instead: `_run_via_worker` is a **new, independent method** that does not touch `_run_monitored_process`'s internals at all, and `run()` gets a single new `if` branch (not a rewrite) that picks between `_run_via_worker` and the existing dispatch. The **one piece that genuinely is extracted** is the small, pure `ANTHROPIC_*` env-var mapping (`_apply_llm_config_env`'s ~20 lines of header-scheme logic) into `opc/layer3_agent/anthropic_env.py`, since both the control-plane path and the worker need the identical BYOK-key-to-env-var mapping and that piece has zero broker-state entanglement.
- `WorkerConnectionRegistry` lives in `opc/layer3_agent/` (engine layer, not the `office_ui` plugin) because `ExternalAgentBroker` (engine layer) must not import from `opc.plugins.office_ui` — the plugin depends on the engine, never the reverse. It is constructed once in `OPCEngine.__init__` and exposed as `engine.worker_registry`; the office-UI plugin's `/worker/ws` route reaches it via `engine.worker_registry`, mirroring how `ws_handler._wire_engine_callbacks(engine)` already wires plugin-level behavior onto engine-level objects post-construction in `server.py`.
- `ExternalAgentBroker`'s new dependencies (`worker_registry`, `credential_provider`, `owner_resolver`) are wired via a new `configure_worker_relay(...)` method called from `server.py` **after** `await engine.initialize()` — not through the constructor — because `credential_provider`/`owner_resolver` depend on `office_ui`-owned stores (`CredentialVault`, `UserStore`) that don't exist yet at the point `OPCEngine.initialize()` constructs the broker. This mirrors the existing `ws_handler._wire_engine_callbacks(engine)` post-init wiring pattern already used in `server.py`.
- This plan does **not** depend on sub-project 3 (BYOK credential vault) being implemented yet. `server.py` wires a small inline stub `credential_provider` that always returns `None` (with a `# TODO` comment) — this makes `_run_via_worker` fail closed with "请先配置你的模型 API Key" until sub-project 3 lands and the stub is swapped for `CredentialVault.get_credentials`. Do not implement `CredentialVault` as part of this plan.
- This plan assumes sub-project 1 (`TenantVmStore`, `TenantVmService`, `/api/vm/bind`) is already implemented (confirmed present in this repo at plan-writing time) — `TenantVmStore.get_user_id_for_auth_token` is a new method added to that existing file.
- Worker-relay routing only applies to the non-interactive (`else`) and interactive-fallback (`elif mode == "interactive":`) batch dispatch paths in `run()` — i.e., whatever `mode` would have produced, once a worker is connected for the task's owner it takes over uniformly. True live-streaming interactive mode (`mode == "interactive" and adapter.supports_interactive()`) is not specially handled by the worker relay in this round; if that mode is selected for a task whose owner has a connected worker, it is *also* routed to the worker (the relay branch is checked first, before the mode dispatch) — the worker only implements the non-interactive spawn/stream/wait cycle, which matches every case that currently reaches `_run_monitored_process` anyway (per Task 4's code below, the branch is inserted before all three mode branches).
- Backend tests run with `python -m pytest opc/plugins/office_ui/tests/<file>.py -q` (office_ui-plugin files) or `tests/<file>.py -q` (layer3_agent files) — matches existing directory conventions.
- Any new WS request type added to the browser-facing `/ws` protocol must go in `docs/FRONTEND_BACKEND_MAP.md` — the new `/worker/ws` endpoint's protocol is a **separate**, non-browser-facing protocol and is documented in this plan/spec instead, not in that file.

---

### Task 1: `WorkerConnectionRegistry` — connection tracking + request/response multiplexing

**Files:**
- Create: `opc/layer3_agent/worker_registry.py`
- Test: `tests/test_worker_registry.py`

**Interfaces:**
- Produces: `class WorkerConnectionRegistry` with `register(user_id: str, connection: Any) -> None`, `unregister(user_id: str) -> None`, `is_connected(user_id: str) -> bool`, `async def dispatch_run_task(user_id: str, task_id: str, message: dict, on_progress: Callable[[str], Awaitable[None]] | None, timeout_seconds: float) -> WorkerTaskOutcome | None`, `async def handle_worker_message(message: dict) -> None`, `async def send_cancel(user_id: str, task_id: str) -> None`; `@dataclass class WorkerTaskOutcome` with fields `returncode: int`, `stdout: str`, `stderr: str`, `resume_session_id: str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worker_registry.py`:

```python
"""Unit tests for WorkerConnectionRegistry's connection tracking and
run_task request/response multiplexing."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry


class WorkerConnectionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_is_connected_false_when_unregistered(self) -> None:
        registry = WorkerConnectionRegistry()
        self.assertFalse(registry.is_connected("user-1"))

    async def test_register_then_is_connected_true(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        self.assertTrue(registry.is_connected("user-1"))

    async def test_unregister_clears_connection(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        registry.unregister("user-1")
        self.assertFalse(registry.is_connected("user-1"))

    async def test_dispatch_run_task_returns_none_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        result = await registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=1)
        self.assertIsNone(result)

    async def test_dispatch_run_task_sends_message_and_waits_for_completion(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=5)
        )
        await asyncio.sleep(0)  # let dispatch_run_task register the pending future
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "hello", "stderr": "", "resume_session_id": "sess-abc",
        })
        outcome = await dispatch_task

        connection.send_json.assert_awaited_once_with({"type": "run_task"})
        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(outcome.stdout, "hello")
        self.assertEqual(outcome.resume_session_id, "sess-abc")

    async def test_dispatch_run_task_forwards_progress_messages(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        received: list[str] = []

        async def _on_progress(text: str) -> None:
            received.append(text)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, _on_progress, timeout_seconds=5)
        )
        await asyncio.sleep(0)
        await registry.handle_worker_message({"type": "progress", "task_id": "task-1", "text": "line one"})
        await registry.handle_worker_message({"type": "progress", "task_id": "task-1", "text": "line two"})
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "", "stderr": "", "resume_session_id": None,
        })
        await dispatch_task

        self.assertEqual(received, ["line one", "line two"])

    async def test_dispatch_run_task_times_out_when_no_response(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        result = await registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=0.05)
        self.assertIsNone(result)

    async def test_send_cancel_sends_cancel_message(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)
        await registry.send_cancel("user-1", "task-1")
        connection.send_json.assert_awaited_once_with({"type": "cancel_task", "task_id": "task-1"})

    async def test_send_cancel_is_a_noop_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        await registry.send_cancel("user-1", "task-1")  # must not raise


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_worker_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.layer3_agent.worker_registry'`

- [ ] **Step 3: Write the implementation**

Create `opc/layer3_agent/worker_registry.py`:

```python
"""In-memory registry of connected opc-worker WebSocket connections, keyed by
user_id, plus request/response multiplexing for run_task dispatch.

Constructed once by OPCEngine and shared by both the office-UI plugin's
/worker/ws route handler (registers connections, forwards incoming messages)
and ExternalAgentBroker (dispatches tasks to a connected user's worker).
Cleared on process restart — workers reconnect and re-register.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class WorkerTaskOutcome:
    returncode: int
    stdout: str
    stderr: str
    resume_session_id: str | None


class _PendingRequest:
    def __init__(self, on_progress: Callable[[str], Awaitable[None]] | None) -> None:
        self.on_progress = on_progress
        self.future: asyncio.Future[WorkerTaskOutcome] = asyncio.get_running_loop().create_future()


class WorkerConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, Any] = {}
        self._pending: dict[str, _PendingRequest] = {}

    def register(self, user_id: str, connection: Any) -> None:
        self._connections[user_id] = connection

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    def is_connected(self, user_id: str) -> bool:
        return user_id in self._connections

    async def dispatch_run_task(
        self,
        user_id: str,
        task_id: str,
        message: dict[str, Any],
        on_progress: Callable[[str], Awaitable[None]] | None,
        timeout_seconds: float,
    ) -> WorkerTaskOutcome | None:
        connection = self._connections.get(user_id)
        if connection is None:
            return None

        pending = _PendingRequest(on_progress)
        self._pending[task_id] = pending
        try:
            await connection.send_json(message)
            try:
                return await asyncio.wait_for(pending.future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return None
        finally:
            self._pending.pop(task_id, None)

    async def handle_worker_message(self, message: dict[str, Any]) -> None:
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

    async def send_cancel(self, user_id: str, task_id: str) -> None:
        connection = self._connections.get(user_id)
        if connection is not None:
            await connection.send_json({"type": "cancel_task", "task_id": task_id})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_registry.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/worker_registry.py tests/test_worker_registry.py
git commit -m "feat: add WorkerConnectionRegistry for run_task dispatch/multiplexing"
```

---

### Task 2: Extract `anthropic_env_for()` — shared BYOK-to-env-var mapping

**Files:**
- Create: `opc/layer3_agent/anthropic_env.py`
- Modify: `opc/layer3_agent/external_broker.py`
- Test: `tests/test_anthropic_env.py`

**Interfaces:**
- Produces: `def anthropic_env_for(api_key: str, api_base: str, default_model: str = "") -> dict[str, str]` — pure function, no broker/adapter dependency.
- Consumes by: `ExternalAgentBroker._apply_llm_config_env` (refactored in this task) and `WorkerRuntime._handle_run_task` (Task 5).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_anthropic_env.py`:

```python
"""Unit tests for the shared BYOK-credential-to-env-var mapping."""

from __future__ import annotations

import unittest

from opc.layer3_agent.anthropic_env import anthropic_env_for


class AnthropicEnvTests(unittest.TestCase):
    def test_first_party_key_without_base_uses_api_key_header(self) -> None:
        env = anthropic_env_for("sk-first-party", "")
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "sk-first-party"})

    def test_relay_key_with_base_uses_auth_token_header(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://relay.example.com")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-relay-key")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_relay_with_default_model_strips_provider_prefix(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com", "anthropic/mimo-v2.5-pro")
        self.assertEqual(env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    def test_relay_with_unprefixed_default_model_passes_through(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com", "mimo-v2.5-pro")
        self.assertEqual(env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    def test_no_key_produces_empty_env(self) -> None:
        env = anthropic_env_for("", "")
        self.assertEqual(env, {})

    def test_base_without_key_sets_base_only(self) -> None:
        env = anthropic_env_for("", "https://relay.example.com")
        self.assertEqual(env, {"ANTHROPIC_BASE_URL": "https://relay.example.com"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_anthropic_env.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.layer3_agent.anthropic_env'`

- [ ] **Step 3: Write the implementation**

Create `opc/layer3_agent/anthropic_env.py`:

```python
"""Maps a BYOK (api_key, api_base, default_model) credential onto the env
vars Claude Code's bundled Anthropic SDK actually reads.

Shared by ExternalAgentBroker._apply_llm_config_env (control-plane native
run path) and WorkerRuntime (VM/worker relay path) so the auth-header-scheme
choice (ANTHROPIC_API_KEY vs ANTHROPIC_AUTH_TOKEN) lives in exactly one place.
"""

from __future__ import annotations


def anthropic_env_for(api_key: str, api_base: str, default_model: str = "") -> dict[str, str]:
    """Claude Code authenticates differently depending on which env var carries
    the key: ANTHROPIC_API_KEY is sent as the x-api-key header (what official
    first-party keys expect), while ANTHROPIC_AUTH_TOKEN is sent as
    Authorization: Bearer (what third-party Claude-compatible relays expect).
    Sending both makes the SDK emit both headers and the request is rejected
    outright, so a custom api_base (i.e. pointed at a relay, not
    api.anthropic.com) always prefers ANTHROPIC_AUTH_TOKEN.
    """
    env: dict[str, str] = {}
    api_key = (api_key or "").strip()
    api_base = (api_base or "").strip()
    default_model = (default_model or "").strip()

    if api_base:
        env["ANTHROPIC_BASE_URL"] = api_base
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if default_model:
            model_name = default_model.split("/", 1)[1] if "/" in default_model else default_model
            if model_name:
                env["ANTHROPIC_MODEL"] = model_name
    elif api_key:
        env["ANTHROPIC_API_KEY"] = api_key

    return env
```

Now refactor `ExternalAgentBroker._apply_llm_config_env` in `opc/layer3_agent/external_broker.py` (lines 105-146) to delegate to it. Add the import near the top of the file, alongside the other `opc.layer3_agent` imports:

```python
from opc.layer3_agent.anthropic_env import anthropic_env_for
```

Replace the body of `_apply_llm_config_env` (keep the method and its docstring, replace everything from `if self._llm_config_provider is None:` onward):

```python
    def _apply_llm_config_env(self, env: dict[str, str]) -> None:
        """Inject the currently-configured LLM api_key/api_base into env, in place.

        Read via a provider callable (not a captured LLMConfig reference) so this
        reflects hot-reloaded config (see OPCEngine._refresh_runtime_config_from_disk)
        without requiring a broker restart. The actual env-var mapping (which
        header scheme to use) lives in anthropic_env.anthropic_env_for, shared
        with WorkerRuntime's identical BYOK-credential-to-env-var need.
        """
        if self._llm_config_provider is None:
            return
        llm_config = self._llm_config_provider()
        api_key = str(getattr(llm_config, "api_key", "") or "")
        api_base = str(getattr(llm_config, "api_base", "") or "")
        default_model = str(getattr(llm_config, "default_model", "") or "")
        env.update(anthropic_env_for(api_key, api_base, default_model))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_anthropic_env.py -v`
Expected: PASS (6 tests)

Run the existing regression test for the method being refactored:

Run: `python -m pytest tests/test_external_broker_llm_env.py -v`
Expected: PASS (this refactor must not change `_apply_llm_config_env`'s observable behavior — same inputs, same env dict produced)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/anthropic_env.py opc/layer3_agent/external_broker.py tests/test_anthropic_env.py
git commit -m "refactor: extract anthropic_env_for as a shared BYOK-to-env-var mapping"
```

---

### Task 3: `TenantVmStore.get_user_id_for_auth_token` + `/worker/ws` endpoint

**Files:**
- Modify: `opc/plugins/office_ui/tenant_vm_store.py`
- Modify: `opc/plugins/office_ui/tests/test_tenant_vm_store.py`
- Create: `opc/plugins/office_ui/worker_ws.py`
- Test: `opc/plugins/office_ui/tests/test_worker_ws.py`

**Interfaces:**
- Consumes: `WorkerConnectionRegistry` (Task 1).
- Produces: `TenantVmStore.get_user_id_for_auth_token(token: str) -> str | None`; `make_worker_ws_handler(vm_store: TenantVmStore, worker_registry: WorkerConnectionRegistry) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.WebSocketResponse]]`.

- [ ] **Step 1: Write the failing tests**

Append to `opc/plugins/office_ui/tests/test_tenant_vm_store.py` (add to the existing `TenantVmStoreTests` class, before the closing of the class body):

```python
    async def test_get_user_id_for_auth_token_round_trips(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        user_id = await self.store.get_user_id_for_auth_token("tok-abc")
        self.assertEqual(user_id, "user-1")

    async def test_get_user_id_for_auth_token_unknown_returns_none(self) -> None:
        user_id = await self.store.get_user_id_for_auth_token("bogus")
        self.assertIsNone(user_id)
```

Create `opc/plugins/office_ui/tests/test_worker_ws.py`:

```python
"""Integration test for the /worker/ws endpoint: token auth + message routing
into WorkerConnectionRegistry."""

from __future__ import annotations

import asyncio
import unittest

import aiosqlite
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore
from opc.plugins.office_ui.worker_ws import make_worker_ws_handler


class WorkerWsTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.db = await aiosqlite.connect(":memory:")
        self.vm_store = TenantVmStore(self.db)
        await self.vm_store.initialize()
        await self.vm_store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        self.registry = WorkerConnectionRegistry()

        app = web.Application()
        app.router.add_get("/worker/ws", make_worker_ws_handler(self.vm_store, self.registry))
        return app

    async def tearDownAsync(self) -> None:
        await self.db.close()
        await super().tearDownAsync()

    async def _wait_for_registration(self, user_id: str = "user-1") -> None:
        for _ in range(50):
            if self.registry.is_connected(user_id):
                return
            await asyncio.sleep(0.01)
        self.fail("worker never registered in time")

    async def test_connection_with_invalid_token_is_rejected(self) -> None:
        async with self.client.ws_connect("/worker/ws?token=bogus") as ws:
            msg = await ws.receive()
            self.assertTrue(ws.closed or msg.type.name in ("CLOSE", "CLOSED", "CLOSING"))

    async def test_connection_with_valid_token_registers_in_registry(self) -> None:
        async with self.client.ws_connect("/worker/ws?token=tok-abc"):
            await self._wait_for_registration()
            self.assertTrue(self.registry.is_connected("user-1"))
        await asyncio.sleep(0.05)  # give the server's finally block a tick to run
        self.assertFalse(self.registry.is_connected("user-1"))

    async def test_progress_message_is_routed_to_registry(self) -> None:
        async with self.client.ws_connect("/worker/ws?token=tok-abc") as ws:
            await self._wait_for_registration()
            received: list[str] = []

            async def _on_progress(text: str) -> None:
                received.append(text)

            dispatch_task = asyncio.ensure_future(
                self.registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, _on_progress, timeout_seconds=5)
            )
            msg = await ws.receive_json()
            self.assertEqual(msg["type"], "run_task")
            await ws.send_json({"type": "progress", "task_id": "task-1", "text": "hello"})
            await ws.send_json({
                "type": "task_complete", "task_id": "task-1", "returncode": 0,
                "stdout": "", "stderr": "", "resume_session_id": None,
            })
            await dispatch_task
            self.assertEqual(received, ["hello"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_store.py opc/plugins/office_ui/tests/test_worker_ws.py -v`
Expected: `test_tenant_vm_store.py` FAILs with `AttributeError: 'TenantVmStore' object has no attribute 'get_user_id_for_auth_token'`; `test_worker_ws.py` FAILs with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.worker_ws'`

- [ ] **Step 3: Write the implementation**

In `opc/plugins/office_ui/tenant_vm_store.py`, add this method at the end of the `TenantVmStore` class (after `update_status`):

```python
    async def get_user_id_for_auth_token(self, token: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT user_id FROM tenant_vms WHERE auth_token = ?", (token,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
```

Create `opc/plugins/office_ui/worker_ws.py`:

```python
"""WebSocket endpoint for opc worker connections (outbound from tenant VMs).

Separate from the browser-facing /ws endpoint handled by WSHandler: different
auth (a VM's own tenant_vms.auth_token, not a user session token) and a
narrower, non-browser-facing message protocol (run_task/progress/
task_complete/cancel_task) documented in
docs/superpowers/specs/2026-07-14-opc-worker-runtime-mode-design.md.
"""

from __future__ import annotations

import aiohttp.web

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore


def make_worker_ws_handler(vm_store: TenantVmStore, worker_registry: WorkerConnectionRegistry):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        token = request.query.get("token", "")
        user_id = await vm_store.get_user_id_for_auth_token(token) if token else None

        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        if user_id is None:
            await ws.close(code=4401, message=b"unauthorized")
            return ws

        worker_registry.register(user_id, ws)
        try:
            async for msg in ws:
                if msg.type == aiohttp.web.WSMsgType.TEXT:
                    try:
                        data = msg.json()
                    except Exception:
                        continue
                    await worker_registry.handle_worker_message(data)
        finally:
            worker_registry.unregister(user_id)
        return ws

    return _handle
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_store.py opc/plugins/office_ui/tests/test_worker_ws.py -v`
Expected: PASS (all tests, including pre-existing `TenantVmStoreTests`)

- [ ] **Step 5: Wire into `engine.py` and `server.py`**

In `opc/engine.py`, add the import near the other `layer3_agent` imports, and construct the registry right after `self.event_bus = EventBus()` (line 371):

```python
from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
```

```python
        self.event_bus = EventBus()
        self.worker_registry = WorkerConnectionRegistry()
```

Add a `configure_worker_relay` method to `ExternalAgentBroker` in `opc/layer3_agent/external_broker.py` — in `__init__` (lines 91-103), add three new attributes after `self._llm_config_provider = llm_config_provider`:

```python
        self._worker_registry = None
        self._credential_provider = None
        self._owner_resolver = None
```

Add the new method right after `__init__`:

```python
    def configure_worker_relay(self, *, worker_registry, credential_provider, owner_resolver) -> None:
        """Wire cross-cutting, office-UI-owned dependencies onto this broker
        post-construction (they don't exist yet when OPCEngine.initialize()
        constructs this broker — see server.py's post-init wiring)."""
        self._worker_registry = worker_registry
        self._credential_provider = credential_provider
        self._owner_resolver = owner_resolver
```

In `opc/plugins/office_ui/server.py`, add the import right after `from opc.plugins.office_ui.bind_routes import make_bind_vm_handler, make_vm_status_handler`:

```python
from opc.plugins.office_ui.worker_ws import make_worker_ws_handler
```

Right after the existing `await engine.initialize()` call (currently the line `await engine.initialize()`), insert:

```python

    # ── Wire cross-cutting deps onto the broker (constructed inside
    # engine.initialize(), but credential_provider/owner_resolver depend on
    # office_ui-owned stores that only exist here) ─────────────────────
    async def _stub_credential_provider(user_id: str):
        # TODO: replace with credential_vault.get_credentials once the
        # per-user BYOK credential vault (sub-project 3) lands.
        return None

    engine.external_broker.configure_worker_relay(
        worker_registry=engine.worker_registry,
        credential_provider=_stub_credential_provider,
        owner_resolver=user_store.get_project_owner,
    )
```

In the "Routes" block, add the new endpoint right after the existing `/api/vm/status` route:

```python
    app.router.add_get("/worker/ws", make_worker_ws_handler(tenant_vm_store, engine.worker_registry))
```

- [ ] **Step 6: Run the broader regression suite**

Run: `python -m pytest opc/plugins/office_ui/tests/ tests/test_worker_registry.py tests/test_anthropic_env.py -q`
Expected: PASS — confirms the new `ExternalAgentBroker.__init__` attributes and `engine.py` import didn't break any existing construction call sites (they're additive-only: new instance attributes defaulting to `None`, no constructor signature change).

- [ ] **Step 7: Commit**

```bash
git add opc/plugins/office_ui/tenant_vm_store.py opc/plugins/office_ui/tests/test_tenant_vm_store.py opc/plugins/office_ui/worker_ws.py opc/plugins/office_ui/tests/test_worker_ws.py opc/engine.py opc/layer3_agent/external_broker.py opc/plugins/office_ui/server.py
git commit -m "feat: add /worker/ws endpoint and wire WorkerConnectionRegistry into the engine/server"
```

---

### Task 4: `ExternalAgentBroker._run_via_worker` + routing branch in `run()`

**Files:**
- Modify: `opc/layer3_agent/external_broker.py`
- Test: `tests/test_external_broker_worker_relay.py`

**Interfaces:**
- Consumes: `WorkerConnectionRegistry.is_connected`/`dispatch_run_task` (Task 1), `self._owner_resolver`/`self._credential_provider` (Task 3's wiring).
- Produces: `ExternalAgentBroker._run_via_worker(*, adapter, task, workspace_path, cmd, metadata, on_progress) -> TaskResult`; `run()` now checks worker-relay eligibility before its existing `mode` dispatch.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_external_broker_worker_relay.py`:

```python
"""Tests for ExternalAgentBroker's worker-relay dispatch branch: when the
task's project owner has a connected worker, route through it instead of
the local subprocess path — and never silently fall back to local execution."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from opc.core.models import Task, TaskStatus
from opc.layer3_agent.external_broker import ExternalAgentBroker
from opc.layer3_agent.worker_registry import WorkerTaskOutcome


def _make_broker() -> ExternalAgentBroker:
    return ExternalAgentBroker(store=AsyncMock(), approval_engine=MagicMock())


def _make_task(project_id: str = "demo") -> Task:
    return Task(id="task-1", session_id="s1", title="t", description="d", project_id=project_id)


class RunViaWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_failed_result_when_relay_not_configured(self) -> None:
        broker = _make_broker()
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)

    async def test_returns_failed_result_when_owner_cannot_be_resolved(self) -> None:
        broker = _make_broker()
        broker.configure_worker_relay(
            worker_registry=MagicMock(),
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value=None),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("未连接", result.content)

    async def test_returns_failed_result_when_worker_not_connected(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = False
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        registry.dispatch_run_task.assert_not_called()

    async def test_returns_failed_result_when_credentials_missing(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=None),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("API Key", result.content)
        registry.dispatch_run_task.assert_not_called()

    async def test_successful_dispatch_returns_done_result_with_resume_id(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(
            return_value=WorkerTaskOutcome(returncode=0, stdout="hi there", stderr="", resume_session_id="sess-1")
        )
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "https://relay.example.com")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={"session_id": "s1"}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.DONE)
        self.assertEqual(result.content, "hi there")
        self.assertEqual(result.artifacts["resume_session_id"], "sess-1")
        self.assertEqual(result.artifacts["session_id"], "s1")  # metadata preserved

        sent_message = registry.dispatch_run_task.await_args.args[2]
        self.assertEqual(sent_message["api_key"], "sk-x")
        self.assertEqual(sent_message["api_base"], "https://relay.example.com")
        self.assertEqual(sent_message["cmd"], ["claude"])

    async def test_nonzero_returncode_produces_failed_result(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(
            return_value=WorkerTaskOutcome(returncode=1, stdout="", stderr="boom", resume_session_id=None)
        )
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.artifacts["stderr"], "boom")

    async def test_dispatch_timeout_produces_failed_result(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(return_value=None)
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_external_broker_worker_relay.py -v`
Expected: FAIL with `AttributeError: 'ExternalAgentBroker' object has no attribute '_run_via_worker'` (and `configure_worker_relay` not existing yet if Task 3 wasn't already applied — Task 3 must be completed before this task)

- [ ] **Step 3: Write the implementation**

In `opc/layer3_agent/external_broker.py`, add a class constant near the top of `ExternalAgentBroker` (alongside other class-level constants, if any — otherwise right after the class docstring/before `__init__`):

```python
    _WORKER_TASK_TIMEOUT_SECONDS = 600
```

Add `_run_via_worker` as a new method, placed right after `configure_worker_relay` (added in Task 3):

```python
    async def _run_via_worker(
        self,
        *,
        adapter: ExternalAgentAdapter,
        task: Task,
        workspace_path: str,
        cmd: list[str],
        metadata: dict,
        on_progress: Callable[[str], Coroutine[Any, Any, None]] | None,
    ) -> TaskResult:
        """Dispatch to the task owner's connected opc worker instead of running
        cmd as a local subprocess. Never falls back to local execution — a
        missing worker/credential is a hard failure, since falling back would
        defeat the whole point of per-user VM isolation."""
        if self._worker_registry is None or self._owner_resolver is None or self._credential_provider is None:
            return TaskResult(status=TaskStatus.FAILED, content="云主机执行未启用", artifacts=dict(metadata))

        project_id = str(getattr(task, "project_id", "") or "default")
        owner_user_id = await self._owner_resolver(project_id)
        if not owner_user_id:
            return TaskResult(status=TaskStatus.FAILED, content="云主机未连接：无法确定任务所属用户", artifacts=dict(metadata))

        if not self._worker_registry.is_connected(owner_user_id):
            return TaskResult(status=TaskStatus.FAILED, content="云主机未连接，请检查绑定状态", artifacts=dict(metadata))

        credentials = await self._credential_provider(owner_user_id)
        if credentials is None:
            return TaskResult(status=TaskStatus.FAILED, content="请先配置你的模型 API Key", artifacts=dict(metadata))
        api_key, api_base = credentials

        async def _forward_progress(text: str) -> None:
            if on_progress is not None:
                await on_progress(text)

        outcome = await self._worker_registry.dispatch_run_task(
            owner_user_id,
            task.id,
            {
                "type": "run_task",
                "task_id": task.id,
                "project_id": project_id,
                "cmd": cmd,
                "api_key": api_key,
                "api_base": api_base,
            },
            _forward_progress,
            timeout_seconds=self._WORKER_TASK_TIMEOUT_SECONDS,
        )

        if outcome is None:
            return TaskResult(status=TaskStatus.FAILED, content="云主机执行超时或连接中断", artifacts=dict(metadata))

        artifacts = dict(metadata)
        artifacts["stderr"] = outcome.stderr
        if outcome.resume_session_id:
            artifacts["resume_session_id"] = outcome.resume_session_id
        status = TaskStatus.DONE if outcome.returncode == 0 else TaskStatus.FAILED
        return TaskResult(status=status, content=outcome.stdout, artifacts=artifacts)
```

Now wire the routing branch into `run()`. The current code (lines 385-417) is:

```python
        if mode == "interactive" and adapter.supports_interactive():
            result = await self._run_interactive(
                adapter,
                task,
                agent_task,
                workspace_path,
                cmd,
                metadata,
                on_progress,
            )
        elif mode == "interactive":
            metadata["interactive_fallback"] = True
            result = await self._run_monitored_process(
                adapter=adapter,
                task=task,
                launch_task=agent_task,
                workspace_path=workspace_path,
                cmd=cmd,
                metadata=metadata,
                on_progress=on_progress,
                allow_prompt_handling=True,
            )
        else:
            result = await self._run_monitored_process(
                adapter=adapter,
                task=task,
                launch_task=agent_task,
                workspace_path=workspace_path,
                cmd=cmd,
                metadata=metadata,
                on_progress=on_progress,
                allow_prompt_handling=True,
            )
```

Replace it with (adds one new branch checked first; the three existing branches are otherwise untouched):

```python
        worker_owner_user_id: str | None = None
        if self._worker_registry is not None and self._owner_resolver is not None:
            candidate_owner = await self._owner_resolver(str(getattr(task, "project_id", "") or "default"))
            if candidate_owner and self._worker_registry.is_connected(candidate_owner):
                worker_owner_user_id = candidate_owner

        if worker_owner_user_id is not None:
            result = await self._run_via_worker(
                adapter=adapter,
                task=task,
                workspace_path=workspace_path,
                cmd=cmd,
                metadata=metadata,
                on_progress=on_progress,
            )
        elif mode == "interactive" and adapter.supports_interactive():
            result = await self._run_interactive(
                adapter,
                task,
                agent_task,
                workspace_path,
                cmd,
                metadata,
                on_progress,
            )
        elif mode == "interactive":
            metadata["interactive_fallback"] = True
            result = await self._run_monitored_process(
                adapter=adapter,
                task=task,
                launch_task=agent_task,
                workspace_path=workspace_path,
                cmd=cmd,
                metadata=metadata,
                on_progress=on_progress,
                allow_prompt_handling=True,
            )
        else:
            result = await self._run_monitored_process(
                adapter=adapter,
                task=task,
                launch_task=agent_task,
                workspace_path=workspace_path,
                cmd=cmd,
                metadata=metadata,
                on_progress=on_progress,
                allow_prompt_handling=True,
            )
```

The existing lines immediately after this block (`artifacts = {**metadata, **(result.artifacts or {})}`, `result.artifacts = artifacts`, `await self._persist_session(...)`, `return result`) are **unchanged** — they already operate on whatever `result` ends up being, regardless of which branch produced it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_external_broker_worker_relay.py -v`
Expected: PASS (7 tests)

Run the full existing broker regression suite to confirm the new branch doesn't change behavior when no worker is configured (the default `self._worker_registry is None` case must behave exactly as before):

Run: `python -m pytest tests/ -k external_broker -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/external_broker.py tests/test_external_broker_worker_relay.py
git commit -m "feat: route claude_code tasks to a connected worker instead of local execution"
```

---

### Task 5: `opc worker start` CLI + `WorkerRuntime`

**Files:**
- Create: `opc/layer3_agent/worker_runtime.py`
- Modify: `opc/cli/app.py`
- Test: `tests/test_worker_runtime.py`

**Interfaces:**
- Consumes: `ClaudeCodeAdapter.start_process`/`extract_resume_session_id` (existing), `anthropic_env_for` (Task 2).
- Produces: `class WorkerRuntime` with `__init__(self, control_plane_url: str, worker_token: str, workspace_root: Path) -> None`, `async def run_forever(self) -> None`; CLI command `opc worker start`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worker_runtime.py`:

```python
"""Unit tests for WorkerRuntime's message handling (run_task/cancel_task).

These test _handle_run_task/_handle_cancel_task directly against a fake ws
and a mocked ClaudeCodeAdapter.start_process — the outer run_forever/
_connect_and_serve reconnect loop is real network plumbing, verified in the
end-to-end task instead of here."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from opc.layer3_agent.worker_runtime import WorkerRuntime


class _FakeStreamReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


def _make_fake_proc(stdout_lines: list[bytes], stderr_lines: list[bytes], returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.stdout = _FakeStreamReader(stdout_lines + [b""])
    proc.stderr = _FakeStreamReader(stderr_lines + [b""])
    proc.wait = AsyncMock(return_value=returncode)
    return proc


class WorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_task_streams_progress_and_completes(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        ws = AsyncMock()
        fake_proc = _make_fake_proc([b"line one\n", b"line two\n"], [], 0)

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process", AsyncMock(return_value=fake_proc)
        ), patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.extract_resume_session_id", return_value="sess-123"
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "demo", "cmd": ["claude", "--print"],
                "api_key": "sk-test", "api_base": "",
            })

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        progress_texts = [m["text"] for m in sent if m["type"] == "progress"]
        self.assertEqual(progress_texts, ["line one\n", "line two\n"])
        final = sent[-1]
        self.assertEqual(final["type"], "task_complete")
        self.assertEqual(final["returncode"], 0)
        self.assertEqual(final["resume_session_id"], "sess-123")
        self.assertEqual(final["stdout"], "line one\nline two\n")

    async def test_run_task_reports_spawn_failure_as_task_complete_with_nonzero_code(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        ws = AsyncMock()

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process",
            AsyncMock(side_effect=OSError("binary not found")),
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "demo", "cmd": ["claude"],
                "api_key": "sk-test", "api_base": "",
            })

        final = ws.send_json.await_args.args[0]
        self.assertEqual(final["type"], "task_complete")
        self.assertNotEqual(final["returncode"], 0)
        self.assertIn("binary not found", final["stderr"])

    async def test_run_task_creates_project_workspace_directory(self) -> None:
        workspace_root = Path(tempfile.mkdtemp())
        runtime = WorkerRuntime("http://localhost:8765", "tok", workspace_root)
        ws = AsyncMock()
        fake_proc = _make_fake_proc([], [], 0)

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process", AsyncMock(return_value=fake_proc)
        ), patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.extract_resume_session_id", return_value=None
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "my-project", "cmd": ["claude"],
                "api_key": "", "api_base": "",
            })

        self.assertTrue((workspace_root / "my-project").is_dir())

    async def test_cancel_task_kills_matching_process(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        fake_process = MagicMock()
        runtime._current_task_id = "task-1"
        runtime._current_process = fake_process
        runtime._handle_cancel_task({"task_id": "task-1"})
        fake_process.kill.assert_called_once()

    async def test_cancel_task_ignores_mismatched_task_id(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        fake_process = MagicMock()
        runtime._current_task_id = "task-1"
        runtime._current_process = fake_process
        runtime._handle_cancel_task({"task_id": "other-task"})
        fake_process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_worker_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.layer3_agent.worker_runtime'`

- [ ] **Step 3: Write the implementation**

Create `opc/layer3_agent/worker_runtime.py`:

```python
"""opc worker runtime: connects outbound to the control plane, receives
run_task/cancel_task messages, spawns Claude Code CLI locally via the
existing ClaudeCodeAdapter, and streams progress/results back.

Runs inside a user's SkyPilot VM (sub-project 1) — never on the control
plane. Reuses layer3_agent adapter code so file/tool operations happen on
this machine's local disk, not proxied from the control plane. The control
plane already built the full `cmd` argv (including any --resume <id> flag)
before sending run_task — this runtime executes it verbatim, it does not
rebuild session-resume arguments itself.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

from opc.layer3_agent.adapters.claude_code import ClaudeCodeAdapter
from opc.layer3_agent.anthropic_env import anthropic_env_for

_RECONNECT_DELAY_SECONDS = 5


class WorkerRuntime:
    def __init__(self, control_plane_url: str, worker_token: str, workspace_root: Path) -> None:
        self._control_plane_url = control_plane_url.rstrip("/")
        self._worker_token = worker_token
        self._workspace_root = workspace_root
        self._current_task_id: str | None = None
        self._current_process: Any = None

    async def run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_serve()
            except (aiohttp.ClientError, ConnectionError, OSError):
                pass
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _connect_and_serve(self) -> None:
        url = f"{self._control_plane_url}/worker/ws?token={self._worker_token}"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                await ws.send_json({"type": "hello"})
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        continue
                    await self._handle_message(ws, data)

    async def _handle_message(self, ws: Any, data: dict) -> None:
        msg_type = data.get("type")
        if msg_type == "run_task":
            await self._handle_run_task(ws, data)
        elif msg_type == "cancel_task":
            self._handle_cancel_task(data)

    async def _handle_run_task(self, ws: Any, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        project_id = str(data.get("project_id") or "default")
        cmd = list(data.get("cmd") or [])
        api_key = str(data.get("api_key") or "")
        api_base = str(data.get("api_base") or "")

        workspace_path = self._workspace_root / project_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        extra_env = anthropic_env_for(api_key, api_base)
        adapter = ClaudeCodeAdapter()

        self._current_task_id = task_id
        try:
            proc = await adapter.start_process(cmd, str(workspace_path), extra_env=extra_env)
        except OSError as exc:
            await ws.send_json({
                "type": "task_complete", "task_id": task_id, "returncode": 1,
                "stdout": "", "stderr": f"spawn failed: {exc}", "resume_session_id": None,
            })
            self._current_task_id = None
            return

        self._current_process = proc
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _drain(stream: Any, sink: list[str], stream_name: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                sink.append(text)
                await ws.send_json({"type": "progress", "task_id": task_id, "stream": stream_name, "text": text})

        await asyncio.gather(
            _drain(proc.stdout, stdout_chunks, "stdout"),
            _drain(proc.stderr, stderr_chunks, "stderr"),
        )
        returncode = await proc.wait()

        output = "".join(stdout_chunks)
        resume_session_id = adapter.extract_resume_session_id(output)

        await ws.send_json({
            "type": "task_complete",
            "task_id": task_id,
            "returncode": returncode,
            "stdout": output,
            "stderr": "".join(stderr_chunks),
            "resume_session_id": resume_session_id,
        })
        self._current_task_id = None
        self._current_process = None

    def _handle_cancel_task(self, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        if task_id and task_id == self._current_task_id and self._current_process is not None:
            self._current_process.kill()
```

In `opc/cli/app.py`, add the new Typer sub-app right before the existing `user_app = typer.Typer(...)` line:

```python
worker_app = typer.Typer(help="Run OpenOPC as a worker on a tenant VM")
app.add_typer(worker_app, name="worker")


@worker_app.command("start")
def worker_start(
    control_plane_url: Optional[str] = typer.Option(
        None, "--control-plane-url", envvar="OPC_CONTROL_PLANE_URL",
        help="Control plane base URL, e.g. https://opc.example.com",
    ),
    token: Optional[str] = typer.Option(
        None, "--token", envvar="OPC_WORKER_TOKEN", help="This VM's auth token from tenant_vms.auth_token",
    ),
    workspace_root: Optional[str] = typer.Option(
        None, "--workspace-root", envvar="OPC_WORKER_WORKSPACE_ROOT", help="Local directory for project workspaces",
    ),
):
    """Connect outbound to the control plane and execute dispatched tasks locally."""
    from opc.layer3_agent.worker_runtime import WorkerRuntime

    if not control_plane_url or not token:
        console.print(
            "[error]Missing --control-plane-url/--token "
            "(or OPC_CONTROL_PLANE_URL/OPC_WORKER_TOKEN env vars)[/error]"
        )
        raise typer.Exit(code=1)

    root = Path(workspace_root or (Path.home() / "opc_workspace"))
    root.mkdir(parents=True, exist_ok=True)
    asyncio.run(WorkerRuntime(control_plane_url, token, root).run_forever())
```

(`Optional`, `Path`, `asyncio`, `console`, and `typer` are already imported at the top of `opc/cli/app.py` — no new imports needed there.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_runtime.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/worker_runtime.py opc/cli/app.py tests/test_worker_runtime.py
git commit -m "feat: add 'opc worker start' CLI command and WorkerRuntime"
```

---

### Task 6: Full-stack + real-VM end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend regression suite**

Run: `python -m pytest tests/ opc/plugins/office_ui/tests/ -q`
Expected: PASS, zero regressions from Tasks 1-5.

- [ ] **Step 2: Extend `tenant_vm.yaml` (sub-project 1's artifact) to install OpenOPC + start the worker**

This step modifies a file owned by sub-project 1 — check `opc/plugins/office_ui/skypilot/tenant_vm.yaml` reflects its current `setup:`/`run:` sections before editing (sub-project 1 was implemented separately; confirm no conflicting in-flight changes before touching this file).

Append to the `setup:` block (after the existing `npm install -g @anthropic-ai/claude-code` line):

```yaml
  pip install openopc  # or: pip install -e /path/to/OpenOPC-main if installing from source
```

Replace the `run:` block (currently `echo "tenant VM ready"`):

```yaml
run: |
  opc worker start --control-plane-url "$OPC_CONTROL_PLANE_URL" --token "$OPC_WORKER_TOKEN"
```

Add an `envs:` section (SkyPilot fills concrete values via `sky launch -e KEY=VALUE`; these are just the declared names):

```yaml
envs:
  OPC_CONTROL_PLANE_URL: ""
  OPC_WORKER_TOKEN: ""
```

`TenantVmService._run_launch`/`_run_start` (sub-project 1) will need `-e OPC_CONTROL_PLANE_URL=<control plane's own public URL> -e OPC_WORKER_TOKEN=<this VM's tenant_vms.auth_token>` added to their `sky launch`/`sky start` subprocess argv — this is a small follow-up edit to `opc/plugins/office_ui/tenant_vm_service.py` needed to make this task's env wiring actually take effect; do it now as part of this verification task since it's required to reach a working end-to-end state, and re-run sub-project 1's existing test suite afterward to confirm no regression:

Run: `python -m pytest opc/plugins/office_ui/tests/test_tenant_vm_service.py -v`
Expected: PASS (unchanged — the `-e` flags are additive argv entries; existing tests assert on `shutil.which`/subprocess mocking, not on exact full argv equality, so check the actual test file before assuming this is a no-op change).

- [ ] **Step 3: Real end-to-end run**

Using the real VM from sub-project 1's own end-to-end task (or bind a fresh one via the browser's "创建云主机" flow):

1. Confirm the worker connects: `sky exec <cluster> "curl -s http://localhost:1/"` is not meaningful here — instead check the control plane's own logs for a line confirming a WS connection on `/worker/ws` (add a `logger.info` there if none exists), or simpler: check `engine.worker_registry.is_connected(<user_id>)` via a debug script.
2. Send a Task Mode chat message with `agent=claude_code` selected, for a project owned by the VM's user. Confirm the response streams into the chat UI (this is the existing `on_progress` → `event_adapter` → browser pipeline, now fed from the worker instead of a local subprocess).
3. Send a **second** message in the same session. Confirm the response demonstrates contextual continuity with the first (e.g., ask "what did I just ask you?") — this is the required multi-turn `--resume` verification.
4. Kill the worker process on the VM mid-task (e.g. `sky exec <cluster> "pkill -f 'opc worker'"`) while a task is in flight; confirm the chat surfaces a clear failure (not a silent hang), and confirm a subsequent message after restarting the worker (`sky exec <cluster> "opc worker start ... &"`) succeeds normally.

- [ ] **Step 4: Report residual known limitations**

Confirm these are true and acceptable (matching the design spec's own non-goals):

- Mid-task worker disconnects are not resumed — the in-flight task fails, the user must resend the message (matches spec's explicit non-goal).
- The live-streaming "interactive" mode is routed through the worker's batch-only spawn/stream/wait cycle rather than a specialized interactive relay — acceptable for this round since it still produces a correct final result, just without the same partial-output cadence local interactive mode has.
- Per-user API key comes from a stub returning `None` until sub-project 3 lands — until then, worker-relay dispatch always fails with "请先配置你的模型 API Key" (this is correct fail-closed behavior, not a bug).
