# 登录后体验优化 + 租户数据隔离 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the cross-user data leak (any project_id is currently readable/writable by any logged-in user), then layer on the login-aware product surface: an identity menu, a global LLM model/API-key settings panel that actually reaches native + external agents without a restart, and a read-only SkyPilot "Nodes" panel.

**Architecture:** D (tenant isolation) ships first and alone — it is a security fix with zero frontend dependency. B/A are shipped together next (A's identity menu is the only entry point to B's settings panel). C ships last and is fully independent of the other three.

**Tech Stack:** Python 3.10+ / aiohttp / aiosqlite / pydantic (backend), React 19 + TypeScript + Vite (frontend), no new dependencies.

## Global Constraints

- Backend tests run with `python -m pytest tests/<file>.py -q` or `python -m pytest opc/plugins/office_ui/tests/<file>.py -q` — match whichever directory the sibling test file for that module already lives in (stores → `opc/plugins/office_ui/tests/`, services → top-level `tests/`).
- Frontend tests run with `npx tsx --test <file>.test.ts` (or `.test.tsx`) from `opc/plugins/office_ui/frontend_src`; there is no DOM renderer in this repo — components that touch `window`/`localStorage`/WebSocket are tested by reading their own source with `readFileSync` and asserting key call-sites/state via `assert.match(source, /regex/)`, per `auth/LoginScreen.test.tsx`.
- Any new WS request type must be added to `docs/FRONTEND_BACKEND_MAP.md` in the same task that introduces it.
- `default` project keeps today's single-user behavior for installs with exactly one account (see Task 3's self-heal); do not special-case `"default"` as always-shared — that would defeat the isolation fix for any install that ends up with 2+ accounts.
- Do not touch `agent_store.py` (Office visual state) — the spec explicitly excludes it from this round (documented known limitation).
- No new `Modal`/`Dialog` abstraction — reuse the existing `.org-create-backdrop`/`.org-create-modal`/`.org-create-header`/`.org-create-panel`/`.org-create-field`/`.org-create-close` CSS classes (`opc/plugins/office_ui/frontend_src/org/org.css:413-598`), matching how `AddConnectorModal.tsx` already reuses them outside the `org/` feature.

---

## Task 1: `UserStore` — project ownership table + methods

**Files:**
- Modify: `opc/plugins/office_ui/user_store.py`
- Test: `opc/plugins/office_ui/tests/test_user_store.py` (existing file — add a new test class)

**Interfaces:**
- Produces: `UserStore.record_project_owner(project_id: str, user_id: str) -> None`, `UserStore.get_project_owner(project_id: str) -> str | None`, `UserStore.list_project_owners() -> dict[str, str]`, `UserStore.get_sole_user_id() -> str | None` (returns the single row's `user_id` from `users` iff there is exactly one row, else `None`).

- [ ] **Step 1: Write the failing tests**

Append to `opc/plugins/office_ui/tests/test_user_store.py` (before the `if __name__ == "__main__":` line at the bottom):

```python
class ProjectOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = UserStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_get_project_owner_returns_none_when_unrecorded(self) -> None:
        owner = await self.store.get_project_owner("alpha")
        self.assertIsNone(owner)

    async def test_record_then_get_project_owner_round_trips(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        owner = await self.store.get_project_owner("alpha")
        self.assertEqual(owner, "user-1")

    async def test_record_project_owner_is_idempotent_first_writer_wins(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        await self.store.record_project_owner("alpha", "user-2")
        owner = await self.store.get_project_owner("alpha")
        self.assertEqual(owner, "user-1")

    async def test_list_project_owners_returns_all_rows(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        await self.store.record_project_owner("beta", "user-2")
        owners = await self.store.list_project_owners()
        self.assertEqual(owners, {"alpha": "user-1", "beta": "user-2"})

    async def test_get_sole_user_id_returns_none_when_no_users(self) -> None:
        sole = await self.store.get_sole_user_id()
        self.assertIsNone(sole)

    async def test_get_sole_user_id_returns_the_only_user(self) -> None:
        await self.store.create_invite_code("CODE1")
        user_id, _ = await self.store.register("alice", "CODE1")
        sole = await self.store.get_sole_user_id()
        self.assertEqual(sole, user_id)

    async def test_get_sole_user_id_returns_none_when_multiple_users(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.create_invite_code("CODE2")
        await self.store.register("alice", "CODE1")
        await self.store.register("bob", "CODE2")
        sole = await self.store.get_sole_user_id()
        self.assertIsNone(sole)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_user_store.py -v -k ProjectOwnershipTests`
Expected: FAIL with `AttributeError: 'UserStore' object has no attribute 'record_project_owner'`

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/user_store.py`, add the table to `initialize()` (right after the existing `sessions` table's `CREATE TABLE` call, before `await self._db.commit()`):

```python
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS project_owners (
                project_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
```

Then add these methods to the `UserStore` class (after `get_user_id_for_token`):

```python
    async def record_project_owner(self, project_id: str, user_id: str) -> None:
        """Record project ownership. First writer wins — a project_id is claimed once."""
        async with self._write_lock:
            await self._db.execute(
                "INSERT OR IGNORE INTO project_owners (project_id, owner_user_id, created_at) VALUES (?, ?, ?)",
                (project_id, user_id, time.time()),
            )
            await self._db.commit()

    async def get_project_owner(self, project_id: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT owner_user_id FROM project_owners WHERE project_id = ?", (project_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def list_project_owners(self) -> dict[str, str]:
        cursor = await self._db.execute("SELECT project_id, owner_user_id FROM project_owners")
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}

    async def get_sole_user_id(self) -> str | None:
        """Return the only user's id, or None if there are zero or 2+ users."""
        cursor = await self._db.execute("SELECT user_id FROM users LIMIT 2")
        rows = await cursor.fetchall()
        return rows[0][0] if len(rows) == 1 else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_user_store.py -v`
Expected: PASS (all tests, including the pre-existing `UserStoreTests` class)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/user_store.py opc/plugins/office_ui/tests/test_user_store.py
git commit -m "feat: add project_owners table and ownership methods to UserStore"
```

---

## Task 2: Wire `user_store` into `OfficeServiceContext`

**Files:**
- Modify: `opc/plugins/office_ui/services/context.py`
- Modify: `opc/plugins/office_ui/ws_handler.py` (both `OfficeServiceContext(...)` construction sites)
- Test: `tests/test_project_service.py` (new — created fully in Task 3, this task just needs `OfficeServiceContext` to accept the param without erroring)

**Interfaces:**
- Consumes: nothing new.
- Produces: `OfficeServiceContext.__init__(..., user_store: Any = None)`, exposed as `self.user_store`.

- [ ] **Step 1: Implement — context.py**

In `opc/plugins/office_ui/services/context.py`, add `user_store` to `OfficeServiceContext.__init__`:

```python
    def __init__(
        self,
        *,
        engine: Any,
        agent_store: Any,
        chat_store: Any,
        event_adapter: Any,
        mode_state: ModeState | None = None,
        user_store: Any = None,
    ) -> None:
        self.root_engine = engine
        self.active_engine = engine
        self.agent_store = agent_store
        self.chat_store = chat_store
        self.event_adapter = event_adapter
        self.user_store = user_store
        self.mode_state = mode_state or ModeState()
```

(Everything else in `__init__` stays exactly as-is — this only adds the one new keyword arg and its assignment.)

- [ ] **Step 2: Implement — ws_handler.py, both construction sites**

In `opc/plugins/office_ui/ws_handler.py`, in `WSHandler.__init__`, find `self.services_context = OfficeServiceContext(` (around line 473) and add `user_store=self._user_store,` to its kwargs:

```python
        self.services_context = OfficeServiceContext(
            engine=engine,
            agent_store=agent_store,
            chat_store=chat_store,
            event_adapter=event_adapter,
            user_store=self._user_store,
            mode_state=ModeState(
                exec_mode=self._exec_mode,
                company_profile=self._company_profile,
                task_preferred_agent=self._task_preferred_agent,
            ),
        )
```

In `_ensure_office_services()` (around line 522), add the same to the fallback construction:

```python
        context = OfficeServiceContext(
            engine=self.engine,
            agent_store=getattr(self, "agent_store", None),
            chat_store=getattr(self, "chat_store", None),
            event_adapter=getattr(self, "event_adapter", None),
            user_store=getattr(self, "_user_store", None),
            mode_state=ModeState(
                exec_mode=getattr(self, "_exec_mode", "task"),
                company_profile=getattr(self, "_company_profile", "corporate"),
                task_preferred_agent=getattr(self, "_task_preferred_agent", "native"),
            ),
        )
```

- [ ] **Step 3: Run the existing test suite to verify nothing broke**

Run: `python -m pytest tests/test_connectors_service.py opc/plugins/office_ui/tests/test_auth_integration.py -v`
Expected: PASS (these construct `OfficeServiceContext`/`WSHandler` directly and must keep working with the new optional param)

- [ ] **Step 4: Commit**

```bash
git add opc/plugins/office_ui/services/context.py opc/plugins/office_ui/ws_handler.py
git commit -m "feat: thread user_store through OfficeServiceContext"
```

---

## Task 3: `ProjectService` — ownership filtering, recording, and access assertion

**Files:**
- Modify: `opc/plugins/office_ui/services/project.py`
- Test: `tests/test_project_service.py` (new)

**Interfaces:**
- Consumes: `OfficeServiceContext.user_store` (Task 2), `UserStore.record_project_owner/get_project_owner/list_project_owners/get_sole_user_id` (Task 1).
- Produces: `ProjectService.list(*, active_project_id=None, owner_user_id: str | None = None)`, `ProjectService.create(project_id, *, active_project_id=None, owner_user_id: str | None = None)`, `ProjectService.assert_access(project_id: str, owner_user_id: str | None) -> None` (raises `ServiceError("project_access_denied", ...)`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_service.py`:

```python
"""Unit tests for ProjectService's per-user project ownership enforcement."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiosqlite

from opc.plugins.office_ui.services.context import ModeState, OfficeServiceContext
from opc.plugins.office_ui.services.models import ServiceError
from opc.plugins.office_ui.services.project import ProjectService
from opc.plugins.office_ui.user_store import UserStore


class ProjectServiceOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(".tmp-test-project-service")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "projects").mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(":memory:")
        self.user_store = UserStore(self.db)
        await self.user_store.initialize()

        fake_engine = SimpleNamespace(opc_home=self.tmp_dir, project_id="default")
        self.context = OfficeServiceContext(
            engine=fake_engine,
            agent_store=MagicMock(),
            chat_store=MagicMock(),
            event_adapter=MagicMock(),
            user_store=self.user_store,
            mode_state=ModeState(),
        )
        self.service = ProjectService(self.context)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def _register(self, username: str, code: str) -> str:
        await self.user_store.create_invite_code(code)
        user_id, _ = await self.user_store.register(username, code)
        assert user_id is not None
        return user_id

    async def test_project_created_by_user_a_not_in_user_bs_list(self) -> None:
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")

        await self.service.create("alpha", owner_user_id=user_a)

        result_b = await self.service.list(owner_user_id=user_b)
        ids_b = {p["id"] for p in result_b.payload["projects"]}
        self.assertNotIn("alpha", ids_b)

        result_a = await self.service.list(owner_user_id=user_a)
        ids_a = {p["id"] for p in result_a.payload["projects"]}
        self.assertIn("alpha", ids_a)

    async def test_user_b_calling_with_user_as_project_id_is_denied(self) -> None:
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")
        await self.service.create("alpha", owner_user_id=user_a)

        with self.assertRaises(ServiceError) as ctx:
            await self.service.assert_access("alpha", user_b)
        self.assertEqual(ctx.exception.code, "project_access_denied")

        await self.service.assert_access("alpha", user_a)  # owner is never denied

    async def test_anonymous_mode_is_unaffected(self) -> None:
        await self.service.create("alpha", owner_user_id=None)
        await self.service.assert_access("alpha", None)
        await self.service.assert_access("alpha", "anonymous")
        result = await self.service.list(owner_user_id=None)
        ids = {p["id"] for p in result.payload["projects"]}
        self.assertIn("alpha", ids)

    async def test_historical_project_is_migrated_to_sole_account(self) -> None:
        # Simulate a pre-existing project directory from before accounts existed.
        (self.tmp_dir / "projects" / "legacy").mkdir(parents=True, exist_ok=True)
        user_a = await self._register("alice", "CODE-A")

        result = await self.service.list(owner_user_id=user_a)
        ids = {p["id"] for p in result.payload["projects"]}
        self.assertIn("legacy", ids)
        self.assertEqual(await self.user_store.get_project_owner("legacy"), user_a)

    async def test_historical_project_stays_unassigned_with_multiple_accounts(self) -> None:
        (self.tmp_dir / "projects" / "legacy").mkdir(parents=True, exist_ok=True)
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")

        result_a = await self.service.list(owner_user_id=user_a)
        result_b = await self.service.list(owner_user_id=user_b)
        self.assertNotIn("legacy", {p["id"] for p in result_a.payload["projects"]})
        self.assertNotIn("legacy", {p["id"] for p in result_b.payload["projects"]})
        self.assertIsNone(await self.user_store.get_project_owner("legacy"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_project_service.py -v`
Expected: FAIL with `TypeError: ProjectService.create() got an unexpected keyword argument 'owner_user_id'` (and `AttributeError: 'ProjectService' object has no attribute 'assert_access'`)

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/services/project.py`, add the self-heal helper and modify `__init__`/`list`/`create`, and add `assert_access`:

```python
class ProjectService:
    def __init__(self, context: OfficeServiceContext) -> None:
        self.context = context
        self._ownership_healed = False

    async def _ensure_ownership_self_heal(self) -> None:
        """One-time, idempotent backfill for projects that predate the account system.

        Only assigns ownership when exactly one account exists — with 2+ accounts,
        an unclaimed historical project cannot be safely attributed to any one of
        them, so it is left unowned (invisible to every account) per spec.
        """
        if self._ownership_healed:
            return
        self._ownership_healed = True
        user_store = self.context.user_store
        if user_store is None:
            return
        sole_user_id = await user_store.get_sole_user_id()
        if sole_user_id is None:
            return
        owners = await user_store.list_project_owners()
        for entry in self.context.list_project_entries():
            project_id = entry["id"]
            if project_id not in owners:
                await user_store.record_project_owner(project_id, sole_user_id)
```

Replace the `list()` method:

```python
    async def list(self, *, active_project_id: str | None = None, owner_user_id: str | None = None) -> ServiceResult:
        await self._ensure_ownership_self_heal()
        active = active_project_id or self.context.active_engine_project_id()
        entries = self.context.list_project_entries()
        user_store = self.context.user_store
        if owner_user_id and owner_user_id != "anonymous" and user_store is not None:
            owners = await user_store.list_project_owners()
            entries = [entry for entry in entries if owners.get(entry["id"]) == owner_user_id]
        return ServiceResult({
            "projects": entries,
            "active_project_id": self.context.normalize_project_id(active),
        })
```

Replace the `create()` method (only the ownership-recording line is new, inserted right before `active = active_project_id or ...`):

```python
    async def create(self, project_id: str, *, active_project_id: str | None = None, owner_user_id: str | None = None) -> ServiceResult:
        project_id = str(project_id or "").strip()
        if not project_id:
            raise ServiceError("missing_project_id", "Missing project_id")
        if not self.context.is_safe_project_id(project_id):
            raise ServiceError("invalid_project_id", "Invalid project_id (use alphanumeric, hyphens, underscores)")

        projects_dir = self.context.project_dir(project_id)
        memory_store = MarkdownMemoryStore(Path(self.context.root_engine.opc_home))
        memory_path = memory_store.memory_path(project_id)
        workplace = self.context.project_workplace(project_id)
        if projects_dir.exists() or memory_path.exists() or workplace.exists():
            raise ServiceError("project_exists", f"Project '{project_id}' already exists")

        projects_dir.mkdir(parents=True, exist_ok=False)
        workplace.mkdir(parents=True, exist_ok=False)
        memory_store.ensure_memory_file(project_id, f"# Project Memory ({project_id})")
        if owner_user_id and owner_user_id != "anonymous" and self.context.user_store is not None:
            await self.context.user_store.record_project_owner(project_id, owner_user_id)
        active = active_project_id or self.context.active_engine_project_id()
        return ServiceResult({
            "action": "create_project",
            "project_id": project_id,
            "projects": self.context.list_project_entries(),
            "active_project_id": self.context.normalize_project_id(active),
        })
```

Add `assert_access` as a new method (placed right after `create`):

```python
    async def assert_access(self, project_id: str, owner_user_id: str | None) -> None:
        """Raise ServiceError if owner_user_id may not read/write project_id.

        Anonymous connections (no UserStore configured, or user_id is None/"anonymous")
        are always allowed through unchanged — this preserves single-machine,
        no-account-system behavior exactly as it was before this feature.
        """
        if not owner_user_id or owner_user_id == "anonymous":
            return
        user_store = self.context.user_store
        if user_store is None:
            return
        await self._ensure_ownership_self_heal()
        normalized = self.context.normalize_project_id(project_id)
        owner = await user_store.get_project_owner(normalized)
        if owner != owner_user_id:
            raise ServiceError(
                "project_access_denied",
                f"You do not have access to project '{normalized}'",
                {"project_id": normalized},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_project_service.py -v`
Expected: PASS (all 5 tests)

Also run the full existing suite for regressions:

Run: `python -m pytest tests/ opc/plugins/office_ui/tests/ -q`
Expected: PASS (no regressions — `list()`/`create()` gained an optional kwarg only, existing callers that omit `owner_user_id` behave exactly as before)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/services/project.py tests/test_project_service.py
git commit -m "feat: add per-user project ownership filtering and access assertion"
```

---

## Task 4: `WSHandler` — enforce ownership on every project-scoped message

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Test: `opc/plugins/office_ui/tests/test_project_ownership_ws.py` (new)

**Interfaces:**
- Consumes: `ProjectService.assert_access` (Task 3).
- Produces: nothing new externally — this task closes the access-control gap for every WS message type that carries `project_id`/`projectId`, plus a connect-time redirect so a newly-connected user is never hard-defaulted onto a project they don't own.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_project_ownership_ws.py`:

```python
"""Full-stack test: two accounts, cross-project WS access must be rejected.

Mirrors test_auth_integration.py's harness (real UserStore/aiosqlite, real
handle_ws route) but adds a second registered account and asserts that
sending a project-scoped message with the other account's project_id is
rejected with `project_access_denied`.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import aiosqlite
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from opc.plugins.office_ui.agent_store import AgentStore
from opc.plugins.office_ui.auth_routes import make_login_handler, make_register_handler
from opc.plugins.office_ui.chat_store import ChatStore
from opc.plugins.office_ui.event_adapter import EventAdapter
from opc.plugins.office_ui.user_store import UserStore
from opc.plugins.office_ui.ws_handler import WSHandler


def _make_stub_engine() -> MagicMock:
    engine = MagicMock()
    engine.project_id = "default"
    engine.skills = None
    engine.org_engine = None
    engine.escalation = None
    engine.company_executor = None
    engine.reorg_manager = None
    engine.event_bus.get_history.return_value = []
    engine.store = AsyncMock()
    engine.store.get_tasks.return_value = []
    engine.store.list_delegation_runs.return_value = []
    engine.on_progress = AsyncMock()
    engine.process_message = AsyncMock(return_value="")
    engine.get_latest_pending_checkpoint_for_session = AsyncMock(return_value=None)
    return engine


class ProjectOwnershipWSTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.user_db = await aiosqlite.connect(":memory:")
        self.agent_db = await aiosqlite.connect(":memory:")
        self.chat_db = await aiosqlite.connect(":memory:")

        self.user_store = UserStore(self.user_db)
        await self.user_store.initialize()
        await self.user_store.create_invite_code("INVITE-A")
        await self.user_store.create_invite_code("INVITE-B")

        self.agent_store = AgentStore(self.agent_db)
        await self.agent_store.initialize()
        self.chat_store = ChatStore(self.chat_db)
        await self.chat_store.initialize()

        self.event_adapter = EventAdapter()
        self.engine = _make_stub_engine()
        self.ws_handler = WSHandler(
            self.engine, self.agent_store, self.chat_store, self.event_adapter, self.user_store
        )

        app = web.Application()
        app.router.add_post("/api/register", make_register_handler(self.user_store))
        app.router.add_post("/api/login", make_login_handler(self.user_store))
        app.router.add_get("/ws", self.ws_handler.handle_ws)
        return app

    async def tearDownAsync(self) -> None:
        await self.ws_handler.shutdown()
        await self.user_db.close()
        await self.agent_db.close()
        await self.chat_db.close()
        await super().tearDownAsync()

    async def _register(self, username: str, invite_code: str) -> str:
        resp = await self.client.post("/api/register", json={"username": username, "invite_code": invite_code})
        data = await resp.json()
        assert data["ok"], data
        return data["token"]

    async def test_user_b_cannot_send_session_message_into_user_as_project(self) -> None:
        token_a = await self._register("alice", "INVITE-A")
        token_b = await self._register("bob", "INVITE-B")

        async with self.client.ws_connect(f"/ws?token={token_a}") as ws_a:
            await ws_a.receive(timeout=5)  # initial snapshot
            await ws_a.send_json({"type": "create_project", "project_id": "alpha"})
            ack = await ws_a.receive_json(timeout=5)
            self.assertTrue(ack["payload"]["ok"], ack)

        async with self.client.ws_connect(f"/ws?token={token_b}") as ws_b:
            await ws_b.receive(timeout=5)  # initial snapshot
            await ws_b.send_json({
                "type": "session_send",
                "project_id": "alpha",
                "task_id": "t1",
                "content": "hi",
            })
            ack = await ws_b.receive_json(timeout=5)
            self.assertFalse(ack["payload"]["ok"])
            self.assertEqual(ack["payload"].get("code"), "project_access_denied")

    async def test_user_bs_project_list_excludes_user_as_project(self) -> None:
        token_a = await self._register("alice", "INVITE-A")
        token_b = await self._register("bob", "INVITE-B")

        async with self.client.ws_connect(f"/ws?token={token_a}") as ws_a:
            await ws_a.receive(timeout=5)
            await ws_a.send_json({"type": "create_project", "project_id": "alpha"})
            await ws_a.receive_json(timeout=5)

        async with self.client.ws_connect(f"/ws?token={token_b}") as ws_b:
            await ws_b.receive(timeout=5)
            await ws_b.send_json({"type": "list_projects"})
            ack = await ws_b.receive_json(timeout=5)
            ids = {p["id"] for p in ack["payload"]["projects"]}
            self.assertNotIn("alpha", ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_project_ownership_ws.py -v`
Expected: FAIL — `test_user_b_cannot_send_session_message_into_user_as_project` gets `ok=False` from the *engine* mock raising unrelated errors, not `project_access_denied` (today nothing checks ownership at all, so bob's request is just processed against the stub engine).

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/ws_handler.py`, add a module-level constant near the top of the file (alongside other module-level constants — place it right above the `class WSHandler:` definition):

```python
# Every WS message type whose payload carries an explicit project_id/projectId
# and must therefore be checked against the caller's ownership before the
# handler runs. Mirrors PROJECT_SCOPED_MESSAGE_TYPES in frontend_src/lib/wsClient.ts,
# plus switch_project/delete_project which also carry an explicit project_id.
_OWNERSHIP_CHECKED_MESSAGE_TYPES = frozenset({
    "collab_sync",
    "kanban_create_board",
    "kanban_create_task",
    "kanban_update_task",
    "kanban_move_task",
    "kanban_delete_board",
    "kanban_delete_task",
    "kanban_assign",
    "kanban_status",
    "kanban_switch_view",
    "run_task",
    "create_session",
    "session_send",
    "session_update_config",
    "session_delete",
    "session_detail",
    "session_stop",
    "session_resume",
    "session_complete",
    "session_update_title",
    "secretary_send",
    "project_index",
    "recovery_action",
    "comms_state",
    "comms_read_message",
    "switch_project",
    "delete_project",
})
```

In `_route_message`, wrap the ownership check into the existing try block, right before `await handler(self, ws, data)`:

```python
            try:
                if msg_type in _OWNERSHIP_CHECKED_MESSAGE_TYPES:
                    project_id = str(data.get("project_id") or data.get("projectId") or "").strip()
                    if project_id:
                        await self._ensure_office_services().project.assert_access(
                            project_id, self._client_user_ids.get(ws)
                        )
                await handler(self, ws, data)
            except Exception as e:
```

Add a `ServiceError` branch to the exception chain in the same method, inserted right before the final generic `else:` (i.e. after the existing `elif isinstance(e, ProjectScopeError):` block and its `try/except`):

```python
                elif isinstance(e, ServiceError):
                    try:
                        await self._send_service_error(ws, e, action=msg_type)
                    except Exception:
                        pass
```

In `_handle_list_projects`, pass the caller's user id:

```python
    async def _handle_list_projects(self, ws: Any, data: dict) -> None:
        """List available projects by scanning the projects directory."""
        result = await self.services.project.list(
            active_project_id=self._client_active_project_id(ws),
            owner_user_id=self._client_user_ids.get(ws),
        )
        await self._send_ack(ws, ok=True, **result.payload)
```

In `_handle_create_project`, pass the caller's user id:

```python
    async def _handle_create_project(self, ws: Any, data: dict) -> None:
        """Create a new project directory."""
        try:
            result = await self.services.project.create(
                data.get("project_id", ""),
                active_project_id=self._client_active_project_id(ws),
                owner_user_id=self._client_user_ids.get(ws),
            )
            await self._send_ack(ws, ok=True, **result.payload)
        except ServiceError as exc:
            await self._send_service_error(ws, exc, action="create_project")
```

Finally, in `handle_ws`, guard the connect-time initial project so a user is never defaulted onto a project owned by someone else. Replace:

```python
            initial_project_id = self._active_engine_project_id()
            self._client_project_ids[ws] = initial_project_id
```

with:

```python
            initial_project_id = self._active_engine_project_id()
            connecting_user_id = self._client_user_ids.get(ws)
            try:
                await self._ensure_office_services().project.assert_access(initial_project_id, connecting_user_id)
            except ServiceError:
                owned = await self._ensure_office_services().project.list(owner_user_id=connecting_user_id)
                owned_ids = [entry["id"] for entry in owned.payload.get("projects", [])]
                if owned_ids:
                    initial_project_id = owned_ids[0]
                    await self.services.project.switch(initial_project_id, include_snapshot=False)
                # else: this account owns no project yet. It will keep seeing the
                # currently-active project's initial snapshot until it creates its
                # own — a known residual gap for brand-new multi-account installs,
                # not covered by this task (create_project is unaffected: it always
                # records the new project under the creator, per Task 3).
            self._client_project_ids[ws] = initial_project_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_project_ownership_ws.py -v`
Expected: PASS (both tests)

Run the full suite for regressions:

Run: `python -m pytest tests/ opc/plugins/office_ui/tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py opc/plugins/office_ui/tests/test_project_ownership_ws.py
git commit -m "fix: enforce per-user project ownership on every project-scoped WS message"
```

---

## Task 5: `SettingsService` — global LLM model / API key read + write

**Files:**
- Create: `opc/plugins/office_ui/services/settings.py`
- Modify: `opc/plugins/office_ui/services/__init__.py`
- Test: `tests/test_settings_service.py` (new)

**Interfaces:**
- Consumes: `OfficeServiceContext.engine.config.llm` (an `LLMConfig` instance, `opc/core/config.py:267`), `OfficeServiceContext.config_lock`, `OfficeServiceContext.persist_runtime_config`, `OfficeServiceContext.rebind_config`.
- Produces: `SettingsService.get_llm_config() -> ServiceResult` (payload: `default_model`, `api_base`, `api_key_set: bool`), `SettingsService.update_llm_config(patch: dict) -> ServiceResult` (same payload shape, echoing the new values).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_service.py`:

```python
"""Unit tests for SettingsService's global LLM config read/write."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from opc.core.config import OPCConfig
from opc.plugins.office_ui.services.context import ModeState, OfficeServiceContext
from opc.plugins.office_ui.services.settings import SettingsService


def _build_context() -> OfficeServiceContext:
    config = OPCConfig()
    engine = SimpleNamespace(config=config, opc_home=SimpleNamespace())
    return OfficeServiceContext(
        engine=engine,
        agent_store=MagicMock(),
        chat_store=MagicMock(),
        event_adapter=MagicMock(),
        mode_state=ModeState(),
    )


class SettingsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_llm_config_reports_key_set_without_leaking_the_value(self) -> None:
        context = _build_context()
        context.engine.config.llm.api_key = "sk-secret"
        context.engine.config.llm.default_model = "anthropic/claude-sonnet-4-20250514"
        service = SettingsService(context)

        result = await service.get_llm_config()

        self.assertEqual(result.payload["default_model"], "anthropic/claude-sonnet-4-20250514")
        self.assertTrue(result.payload["api_key_set"])
        self.assertNotIn("api_key", result.payload)

    async def test_update_llm_config_persists_and_rebinds(self) -> None:
        context = _build_context()
        service = SettingsService(context)

        with patch.object(OPCConfig, "save") as save_mock:
            result = await service.update_llm_config({
                "default_model": "anthropic/claude-opus-4-1",
                "api_base": "https://proxy.example.com",
                "api_key": "sk-new-key",
            })

        save_mock.assert_called_once()
        self.assertEqual(context.engine.config.llm.default_model, "anthropic/claude-opus-4-1")
        self.assertEqual(context.engine.config.llm.api_base, "https://proxy.example.com")
        self.assertEqual(context.engine.config.llm.api_key, "sk-new-key")
        self.assertTrue(result.payload["api_key_set"])

    async def test_update_llm_config_blank_api_key_does_not_clear_existing_key(self) -> None:
        context = _build_context()
        context.engine.config.llm.api_key = "sk-existing"
        service = SettingsService(context)

        with patch.object(OPCConfig, "save"):
            await service.update_llm_config({"default_model": "anthropic/claude-opus-4-1", "api_key": ""})

        self.assertEqual(context.engine.config.llm.api_key, "sk-existing")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.services.settings'`

- [ ] **Step 3: Implement**

Create `opc/plugins/office_ui/services/settings.py`:

```python
"""Global LLM model / API key settings, shared by Office UI."""

from __future__ import annotations

from typing import Any

from .context import OfficeServiceContext
from .models import ServiceResult


class SettingsService:
    def __init__(self, context: OfficeServiceContext) -> None:
        self.context = context

    async def get_llm_config(self) -> ServiceResult:
        llm = self.context.engine.config.llm
        return ServiceResult({
            "default_model": llm.default_model,
            "api_base": llm.api_base,
            "api_key_set": bool(llm.api_key),
        })

    async def update_llm_config(self, patch: dict[str, Any]) -> ServiceResult:
        async with self.context.config_lock:
            llm = self.context.engine.config.llm
            new_model = str(patch.get("default_model") or "").strip()
            if new_model:
                llm.default_model = new_model
            if "api_base" in patch:
                llm.api_base = str(patch.get("api_base") or "").strip()
            new_key = str(patch.get("api_key") or "").strip()
            if new_key:
                llm.api_key = new_key
            if self.context.persist_runtime_config is not None:
                self.context.persist_runtime_config()
            else:
                self.context.engine.config.save()
            self.context.rebind_config(self.context.engine.config)
        return await self.get_llm_config()
```

In `opc/plugins/office_ui/services/__init__.py`, add the import, wire it into `OfficeServices.__init__`, and add it to `__all__`:

```python
from .settings import SettingsService
```

```python
        self.settings = SettingsService(context)
```

```python
    "SettingsService",
```

(Insert each in its existing alphabetical position alongside the other imports/attributes/`__all__` entries.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_service.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/services/settings.py opc/plugins/office_ui/services/__init__.py tests/test_settings_service.py
git commit -m "feat: add SettingsService for global LLM model/API key config"
```

---

## Task 6: WS wiring for `get_llm_config` / `update_llm_config`

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Modify: `docs/FRONTEND_BACKEND_MAP.md`
- Test: `opc/plugins/office_ui/tests/test_settings_ws.py` (new)

**Interfaces:**
- Consumes: `SettingsService.get_llm_config`/`update_llm_config` (Task 5).
- Produces: WS request types `get_llm_config` (no payload) and `update_llm_config` (`{"type": "update_llm_config", "patch": {...}}`), both replying via `ack`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_settings_ws.py`:

```python
"""WS-level tests for get_llm_config / update_llm_config."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from opc.core.config import OPCConfig
from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler() -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.engine.config = OPCConfig()
    handler.agent_store = MagicMock()
    handler.chat_store = MagicMock()
    handler.event_adapter = MagicMock()
    handler._user_store = None
    handler._exec_mode = "task"
    handler._company_profile = "corporate"
    handler._task_preferred_agent = "native"
    return handler


class SettingsWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_llm_config_acks_current_values(self) -> None:
        handler = _make_handler()
        handler.engine.config.llm.default_model = "anthropic/claude-sonnet-4-20250514"
        ws = AsyncMock()
        await handler._handle_get_llm_config(ws, {})
        sent = ws.send_json.await_args.args[0] if ws.send_json.await_args else None
        # _send_ack routes through _safe_send_json -> ws.send_json in this fake.
        self.assertIsNotNone(sent)
        self.assertEqual(sent["payload"]["default_model"], "anthropic/claude-sonnet-4-20250514")

    async def test_update_llm_config_applies_patch(self) -> None:
        handler = _make_handler()
        from unittest.mock import patch as mock_patch
        ws = AsyncMock()
        with mock_patch.object(OPCConfig, "save"):
            await handler._handle_update_llm_config(ws, {"patch": {"default_model": "anthropic/claude-opus-4-1"}})
        self.assertEqual(handler.engine.config.llm.default_model, "anthropic/claude-opus-4-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_settings_ws.py -v`
Expected: FAIL with `AttributeError: 'WSHandler' object has no attribute '_handle_get_llm_config'`

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/ws_handler.py`, add the two handlers near the other project-management handlers (e.g. right after `_handle_switch_project`):

```python
    async def _handle_get_llm_config(self, ws: Any, data: dict) -> None:
        try:
            result = await self._ensure_office_services().settings.get_llm_config()
            await self._send_ack(ws, ok=True, **result.payload)
        except ServiceError as exc:
            await self._send_service_error(ws, exc, action="get_llm_config")

    async def _handle_update_llm_config(self, ws: Any, data: dict) -> None:
        try:
            result = await self._ensure_office_services().settings.update_llm_config(data.get("patch", {}) or {})
            await self._send_ack(ws, ok=True, **result.payload)
        except ServiceError as exc:
            await self._send_service_error(ws, exc, action="update_llm_config")
```

Register both in the `_HANDLERS` dict (alongside the other project-management entries, e.g. next to `"list_projects": _handle_list_projects,`):

```python
        "get_llm_config":      _handle_get_llm_config,
        "update_llm_config":   _handle_update_llm_config,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_settings_ws.py -v`
Expected: PASS

- [ ] **Step 5: Document in FRONTEND_BACKEND_MAP.md**

In `docs/FRONTEND_BACKEND_MAP.md`, add a new section after "一、项目管理" (renumber is not required — insert as a new numbered section, e.g. before "二、会话管理"):

```markdown
## 十八、全局模型 / API Key 设置

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 读取模型配置 | SettingsPanel | `get_llm_config` | `_handle_get_llm_config` | `settings.get_llm_config` | `ack` |
| 保存模型配置 | SettingsPanel | `update_llm_config` | `_handle_update_llm_config` | `settings.update_llm_config` | `ack` |
```

- [ ] **Step 6: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py opc/plugins/office_ui/tests/test_settings_ws.py docs/FRONTEND_BACKEND_MAP.md
git commit -m "feat: wire get_llm_config/update_llm_config WS request types"
```

---

## Task 7: Hot-reload `llm_config.yaml` in `OPCEngine`

**Files:**
- Modify: `opc/engine.py`
- Test: `tests/test_runtime_config_enforcement.py` (existing file — add a new test method)

**Interfaces:**
- Consumes: nothing new — this makes `self.config.llm`/`self.llm` track `llm_config.yaml` on disk the same way `system_config.yaml` is already tracked.
- Produces: after `_refresh_runtime_config_from_disk()` detects `llm_config.yaml` changed, `self.config.llm`, `self.llm` (a fresh `LLMProvider`), and `self.history_compactor.llm` all reflect the new file.

- [ ] **Step 1: Write the failing test**

In `tests/test_runtime_config_enforcement.py`, add this test method inside `RuntimeConfigEnforcementTests` (near `test_runtime_refresh_updates_timeout_and_reloads_dependencies`):

```python
    async def test_runtime_refresh_hot_reloads_llm_config(self) -> None:
        with _workspace_tempdir() as opc_home:
            config_dir = opc_home / "config"
            config_dir.mkdir(parents=True, exist_ok=True)

            engine = OPCEngine(config=OPCConfig(), opc_home=opc_home)
            engine.company_executor = SimpleNamespace(work_item_timeout=3600)
            engine.approval_engine = SimpleNamespace(config=engine.config.autonomy)
            engine.adapter_registry = SimpleNamespace(config=None, initialize=AsyncMock())
            engine.org_engine = SimpleNamespace(
                config=None,
                reload_from_config=MagicMock(),
                configure_task_mode_tools=MagicMock(),
            )
            original_llm = engine.llm
            original_history_compactor_llm = engine.history_compactor.llm

            (config_dir / "llm_config.yaml").write_text(
                yaml.safe_dump({"llm": {"default_model": "anthropic/claude-opus-4-1", "api_key": "sk-new"}}),
                encoding="utf-8",
            )

            await engine._refresh_runtime_config_from_disk()

            self.assertEqual(engine.config.llm.default_model, "anthropic/claude-opus-4-1")
            self.assertEqual(engine.config.llm.api_key, "sk-new")
            self.assertIsNot(engine.llm, original_llm)
            self.assertEqual(engine.llm.config.api_key, "sk-new")
            self.assertIs(engine.history_compactor.llm, engine.llm)
            self.assertIsNot(engine.history_compactor.llm, original_history_compactor_llm)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_runtime_config_enforcement.py -v -k test_runtime_refresh_hot_reloads_llm_config`
Expected: FAIL — `engine.config.llm.default_model` stays at the constructor default because `llm_config.yaml` is not in the tracked signature and is never copied back.

- [ ] **Step 3: Implement**

In `opc/engine.py`, add `"llm_config.yaml"` to the tracked tuple in `_runtime_config_signature_for`:

```python
    def _runtime_config_signature_for(self, config_dir: Path) -> tuple[tuple[str, float], ...]:
        tracked = (
            "system_config.yaml",
            "agent_config.yaml",
            "llm_config.yaml",
            "company_corporate_config.yaml",
        )
```

In `_refresh_runtime_config_from_disk`, add the LLM copy-back and provider rebuild right after the existing `self.config.system = loaded.system` / `self.config.agents = loaded.agents` / `self.config.autonomy = loaded.autonomy` lines:

```python
        loaded = OPCConfig.load(config_dir)
        self.config.system = loaded.system
        self.config.agents = loaded.agents
        self.config.autonomy = loaded.autonomy
        self.config.llm = loaded.llm
        self.llm = LLMProvider(self.config.llm, opc_home=self.opc_home)
        if self.history_compactor is not None:
            self.history_compactor.llm = self.llm
        self._runtime_config_signature = signature
```

(`LLMProvider` is already imported at the top of `engine.py` — it is used two lines below in `initialize()` to build `self.llm` originally, so no new import is needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_runtime_config_enforcement.py -v -k test_runtime_refresh_hot_reloads_llm_config`
Expected: PASS

Run the full file for regressions:

Run: `python -m pytest tests/test_runtime_config_enforcement.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opc/engine.py tests/test_runtime_config_enforcement.py
git commit -m "feat: hot-reload llm_config.yaml and rebuild LLMProvider on change"
```

---

## Task 8: Inject configured API key/base URL into external-agent subprocess env

**Files:**
- Modify: `opc/layer3_agent/external_broker.py`
- Modify: `opc/engine.py` (constructor wiring only)
- Test: `tests/test_external_broker_llm_env.py` (new)

**Interfaces:**
- Consumes: `OPCEngine.config.llm` (read fresh at spawn time via a provider callable, so it reflects Task 7's hot-reload without restarting).
- Produces: `ExternalAgentBroker.__init__(..., llm_config_provider: Callable[[], Any] | None = None)`. When the provider returns an `LLMConfig` with a non-empty `api_key`, the spawned subprocess's env gets `ANTHROPIC_API_KEY` (and `ANTHROPIC_BASE_URL` if `api_base` is set), added to `comms_env` before it becomes `extra_env` for `adapter.start_process(...)`.

> **Deviation from the design spec:** the spec named `claude_code.py`'s `agent_home_env_vars()` as the fix point. Investigation found `agent_home_env_vars()` is only invoked when `company_collaboration_enabled_for_task(task)` is true (`external_broker.py:611`) — a plain Task Mode chat never reaches it, which is exactly the reported "Missing Anthropic API Key" bug. The actual unconditional env dict for every external-agent spawn is `comms_env`, built in `_run_monitored_process` before that conditional branch. Injecting there fixes the real bug path; `agent_home_env_vars()` is left untouched (it still serves its original collaboration-CLI-installation purpose).

- [ ] **Step 1: Write the failing test**

Create `tests/test_external_broker_llm_env.py`:

```python
"""Tests that ExternalAgentBroker injects the configured LLM API key/base
into the external agent's spawn env, without clobbering an operator's own
ANTHROPIC_API_KEY when no key is configured."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from opc.core.config import LLMConfig
from opc.layer3_agent.external_broker import ExternalAgentBroker
from opc.core.models import Task


def _make_broker(llm_config: LLMConfig) -> ExternalAgentBroker:
    broker = ExternalAgentBroker(
        store=AsyncMock(),
        approval_engine=MagicMock(),
        task_preparer=None,
        communication=None,
    )
    broker._llm_config_provider = lambda: llm_config
    return broker


class ExternalBrokerLLMEnvTests(unittest.TestCase):
    def test_llm_env_vars_added_when_key_configured(self) -> None:
        broker = _make_broker(LLMConfig(api_key="sk-configured", api_base="https://proxy.example.com"))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-configured")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://proxy.example.com")

    def test_no_env_vars_added_when_key_not_configured(self) -> None:
        broker = _make_broker(LLMConfig(api_key="", api_base=""))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def test_no_provider_is_a_no_op(self) -> None:
        broker = ExternalAgentBroker(store=AsyncMock(), approval_engine=MagicMock())
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env, {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_external_broker_llm_env.py -v`
Expected: FAIL with `AttributeError: 'ExternalAgentBroker' object has no attribute '_apply_llm_config_env'`

- [ ] **Step 3: Implement**

In `opc/layer3_agent/external_broker.py`, update `__init__` to accept the provider:

```python
    def __init__(
        self,
        store: OPCStore,
        approval_engine: ApprovalEngine,
        task_preparer: Callable[[Task], Coroutine[Any, Any, Task]] | None = None,
        communication: CommunicationManager | None = None,
        llm_config_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.store = store
        self.approval_engine = approval_engine
        self.task_preparer = task_preparer
        self.communication = communication
        self._llm_config_provider = llm_config_provider
```

Add the helper method (near the other small helpers, e.g. right after `__init__`):

```python
    def _apply_llm_config_env(self, env: dict[str, str]) -> None:
        """Inject the currently-configured LLM api_key/api_base into env, in place.

        Read via a provider callable (not a captured LLMConfig reference) so this
        reflects hot-reloaded config (see OPCEngine._refresh_runtime_config_from_disk)
        without requiring a broker restart.
        """
        if self._llm_config_provider is None:
            return
        llm_config = self._llm_config_provider()
        api_key = str(getattr(llm_config, "api_key", "") or "").strip()
        api_base = str(getattr(llm_config, "api_base", "") or "").strip()
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if api_base:
            env["ANTHROPIC_BASE_URL"] = api_base
```

In `_run_monitored_process`, call it right after `comms_env` is initialized (before the `collaboration_enabled` branch):

```python
        comms_env: dict[str, str] = self._memory_env(task)
        self._apply_llm_config_env(comms_env)
        collaboration_enabled = company_collaboration_enabled_for_task(task)
```

In `opc/engine.py`, wire the provider at construction (around line 630):

```python
        self.external_broker = ExternalAgentBroker(
            self.store,
            self.approval_engine,
            task_preparer=self._build_external_agent_task,
            communication=self.communication,
            llm_config_provider=lambda: self.config.llm,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_external_broker_llm_env.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/layer3_agent/external_broker.py opc/engine.py tests/test_external_broker_llm_env.py
git commit -m "fix: inject configured ANTHROPIC_API_KEY/BASE_URL into external agent spawn env"
```

---

## Task 9: Frontend `wsClient` — `getLlmConfig` / `updateLlmConfig`

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`
- Test: `opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts` (new — first test file for this module, so check none exists before creating)

**Interfaces:**
- Produces: `VisualSocketClient.getLlmConfig(): void`, `VisualSocketClient.updateLlmConfig(patch: { default_model?: string; api_base?: string; api_key?: string }): void`, and two new optional `SocketHandlers` callbacks `onGetLlmConfig?: (payload: { default_model: string; api_base: string; api_key_set: boolean }) => void` and `onUpdateLlmConfig?: (payload: { ok: boolean; default_model?: string; api_base?: string; api_key_set?: boolean; error?: string }) => void`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`:

```ts
// Source-text regex test — matches the App.test.tsx convention for modules
// that wrap a live WebSocket and can't be exercised without a real socket.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'wsClient.ts'), 'utf-8')

assert.match(source, /getLlmConfig\(\): void \{\s*this\.send\(\{ type: 'get_llm_config' \}\)/, 'getLlmConfig must send a get_llm_config message')
assert.match(source, /updateLlmConfig\(patch:/, 'updateLlmConfig must accept a patch object')
assert.match(source, /type: 'update_llm_config', patch/, 'updateLlmConfig must send patch in the payload')
assert.match(source, /onGetLlmConfig\?:/, 'SocketHandlers must declare onGetLlmConfig')
assert.match(source, /onUpdateLlmConfig\?:/, 'SocketHandlers must declare onUpdateLlmConfig')
assert.match(source, /case 'get_llm_config':\s*this\.handlers\.onGetLlmConfig\?\.\(parsed\.payload/, 'handleMessage must dispatch get_llm_config to onGetLlmConfig')
assert.match(source, /case 'update_llm_config':\s*this\.handlers\.onUpdateLlmConfig\?\.\(parsed\.payload/, 'handleMessage must dispatch update_llm_config to onUpdateLlmConfig')

console.log('wsClient.test.ts passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
Expected: FAIL — `AssertionError` on the first `getLlmConfig` regex (method doesn't exist yet)

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`, add the two handler declarations to the `SocketHandlers` interface, next to the other `org_saved_*` handlers:

```ts
  onGetLlmConfig?: (payload: { default_model: string; api_base: string; api_key_set: boolean }) => void
  onUpdateLlmConfig?: (payload: { ok: boolean; default_model?: string; api_base?: string; api_key_set?: boolean; error?: string }) => void
```

Add the two send methods to `VisualSocketClient`, next to `orgSavedList`/`orgSavedLoad`:

```ts
  getLlmConfig(): void {
    this.send({ type: 'get_llm_config' })
  }

  updateLlmConfig(patch: { default_model?: string; api_base?: string; api_key?: string }): void {
    this.send({ type: 'update_llm_config', patch })
  }
```

Add the two dispatch cases inside `handleMessage`'s `switch`, next to the `org_saved_*` cases:

```ts
    case 'get_llm_config':
      this.handlers.onGetLlmConfig?.(parsed.payload as { default_model: string; api_base: string; api_key_set: boolean })
      break
    case 'update_llm_config':
      this.handlers.onUpdateLlmConfig?.(parsed.payload as { ok: boolean; default_model?: string; api_base?: string; api_key_set?: boolean; error?: string })
      break
```

`get_llm_config`/`update_llm_config` are not project-scoped — do not add them to `PROJECT_SCOPED_MESSAGE_TYPES`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
Expected: PASS, prints `wsClient.test.ts passed`

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/lib/wsClient.ts opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts
git commit -m "feat: add getLlmConfig/updateLlmConfig to wsClient"
```

---

## Task 10: Frontend `SettingsPanel` component

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx`
- Create: `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`

**Interfaces:**
- Consumes: nothing directly from `wsClient` — follows this codebase's established convention (see `OrgTab.tsx`'s props in `App.tsx:2418-2465`) where every child component is purely presentational: it receives data + `onX` callbacks as props, and `App.tsx` alone owns the `VisualSocketClient` instance and all response state.
- Produces: `SettingsPanel({ open, onClose, llmConfig, onRequestLlmConfig, onSaveLlmConfig, saveMessage }: SettingsPanelProps)` — mounted from `IdentityMenu` in Task 11, which forwards these same props from `App.tsx`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`:

```tsx
// Source-text regex test — matches LoginScreen.test.tsx's convention for
// components that touch browser globals and can't be rendered under plain
// Node without a DOM.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'SettingsPanel.tsx'), 'utf-8')

assert.match(source, /if \(!open\) return null/, 'SettingsPanel must not render when closed')
assert.match(source, /onRequestLlmConfig\(\)/, 'SettingsPanel must request current config on open')
assert.match(source, /onSaveLlmConfig\(/, 'SettingsPanel must call onSaveLlmConfig on save')
assert.match(source, /org-create-backdrop/, 'SettingsPanel must reuse the shared modal backdrop class')
assert.match(source, /org-create-modal/, 'SettingsPanel must reuse the shared modal panel class')
assert.match(source, /type="password"/, 'API key field must be a password input')
assert.doesNotMatch(source, /VisualSocketClient/, 'SettingsPanel must stay presentational — no direct wsClient dependency')

console.log('SettingsPanel.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
Expected: FAIL — `ENOENT` reading `SettingsPanel.tsx` (file does not exist yet)

- [ ] **Step 3: Implement**

Create `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx`:

```tsx
import { useEffect, useState } from 'react'

export interface LlmConfigPayload {
  default_model: string
  api_base: string
  api_key_set: boolean
}

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
}

export function SettingsPanel({ open, onClose, llmConfig, onRequestLlmConfig, onSaveLlmConfig, saveMessage }: SettingsPanelProps) {
  const [defaultModel, setDefaultModel] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    if (!open) return
    onRequestLlmConfig()
  }, [open, onRequestLlmConfig])

  useEffect(() => {
    if (!llmConfig) return
    setDefaultModel(llmConfig.default_model)
    setApiBase(llmConfig.api_base)
  }, [llmConfig])

  useEffect(() => {
    if (saveMessage === 'Saved') setApiKey('')
  }, [saveMessage])

  if (!open) return null

  const handleSave = () => {
    onSaveLlmConfig({
      default_model: defaultModel,
      api_base: apiBase,
      ...(apiKey ? { api_key: apiKey } : {}),
    })
  }

  return (
    <div className="org-create-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="org-create-modal" role="dialog" aria-modal="true" aria-labelledby="settings-panel-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">Settings</span>
            <h3 id="settings-panel-title" className="org-create-title">Model / API Key</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">x</button>
        </div>
        <div className="org-create-panel">
          <label className="org-create-field">
            <span>Model</span>
            <input value={defaultModel} onChange={e => setDefaultModel(e.target.value)} placeholder="anthropic/claude-sonnet-4-20250514" />
          </label>
          <label className="org-create-field">
            <span>API Key {llmConfig?.api_key_set && !apiKey ? '(already set)' : ''}</span>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={llmConfig?.api_key_set ? 'Leave blank to keep current key' : ''} />
          </label>
          <label className="org-create-field">
            <span>Base URL</span>
            <input value={apiBase} onChange={e => setApiBase(e.target.value)} placeholder="(default)" />
          </label>
          {saveMessage && <div className="org-create-eyebrow">{saveMessage}</div>}
          <button type="button" className="org-create-close" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
Expected: PASS, prints `SettingsPanel.test.tsx passed`

Run typecheck for the changed file:

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors attributable to `auth/SettingsPanel.tsx` (repo has pre-existing unrelated errors elsewhere — ignore those)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx
git commit -m "feat: add SettingsPanel component for global LLM model/API key config"
```

---

## Task 11: Frontend `IdentityMenu` component + wire into `App.tsx` rail

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/auth/IdentityMenu.tsx`
- Create: `opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
- Create: `opc/plugins/office_ui/frontend_src/auth/identityMenu.css`
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx`

**Interfaces:**
- Consumes: `getStoredUsername()`, `clearSession()` (`lib/auth.ts`, already exist), `SettingsPanel` (Task 10, same `llmConfig`/`onRequestLlmConfig`/`onSaveLlmConfig`/`saveMessage` props, forwarded straight through — `IdentityMenu` owns no LLM-config state itself, matching the rest of this codebase's App.tsx-owns-state convention).
- Produces: `IdentityMenu(props: IdentityMenuProps)` where `IdentityMenuProps` is `SettingsPanel`'s props minus `open`/`onClose` (those become internal state) — renders nothing when `getStoredUsername()` returns `null` (anonymous mode, unchanged behavior).

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`:

```tsx
// Source-text regex test, same convention as LoginScreen.test.tsx.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'IdentityMenu.tsx'), 'utf-8')

assert.match(source, /getStoredUsername\(\)/, 'IdentityMenu must read the stored username')
assert.match(source, /if \(!username\) return null/, 'IdentityMenu must render nothing in anonymous mode')
assert.match(source, /clearSession\(\)/, 'IdentityMenu must clear the session on logout')
assert.match(source, /window\.location\.reload\(\)/, 'IdentityMenu must reload the page after logout')
assert.match(source, /<SettingsPanel/, 'IdentityMenu must mount SettingsPanel')
assert.doesNotMatch(source, /VisualSocketClient/, 'IdentityMenu must stay presentational — no direct wsClient dependency')

console.log('IdentityMenu.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
Expected: FAIL — `ENOENT` reading `IdentityMenu.tsx`

- [ ] **Step 3: Implement**

Create `opc/plugins/office_ui/frontend_src/auth/identityMenu.css`:

```css
.identity-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.identity-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.identity-avatar:hover {
  border-color: var(--accent);
}

.identity-popover {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  min-width: 200px;
  z-index: 80;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  padding: 6px;
}

.identity-popover-username {
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}

.identity-popover-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  background: none;
  border: none;
  border-radius: var(--radius-xs);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}

.identity-popover-item:hover {
  background: var(--surface-hover);
}
```

Create `opc/plugins/office_ui/frontend_src/auth/IdentityMenu.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { clearSession, getStoredUsername } from '../lib/auth'
import { SettingsPanel, type LlmConfigPayload } from './SettingsPanel'
import './identityMenu.css'

interface IdentityMenuProps {
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
}

export function IdentityMenu({ llmConfig, onRequestLlmConfig, onSaveLlmConfig, saveMessage }: IdentityMenuProps) {
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const username = getStoredUsername()

  useEffect(() => {
    const onOutsideClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onOutsideClick)
    return () => document.removeEventListener('mousedown', onOutsideClick)
  }, [])

  if (!username) return null

  const handleLogout = () => {
    clearSession()
    window.location.reload()
  }

  return (
    <div className="identity-wrap" ref={wrapperRef}>
      <button type="button" className="identity-avatar" onClick={() => setOpen(o => !o)} title={username}>
        {username.charAt(0).toUpperCase()}
      </button>
      {open && (
        <div className="identity-popover" role="menu">
          <div className="identity-popover-username">{username}</div>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={() => { setSettingsOpen(true); setOpen(false) }}>
            模型 / API Key 设置
          </button>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      )}
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        llmConfig={llmConfig}
        onRequestLlmConfig={onRequestLlmConfig}
        onSaveLlmConfig={onSaveLlmConfig}
        saveMessage={saveMessage}
      />
    </div>
  )
}
```

In `opc/plugins/office_ui/frontend_src/App.tsx`, add the import near the other top-level imports:

```tsx
import { IdentityMenu } from './auth/IdentityMenu'
```

Add state for the LLM config panel, next to the other `useState` declarations (e.g. near `orgToast`/`marketPreviewData`):

```tsx
const [llmConfig, setLlmConfig] = useState<{ default_model: string; api_base: string; api_key_set: boolean } | null>(null)
const [llmConfigSaveMessage, setLlmConfigSaveMessage] = useState('')
```

Add two handlers to the `VisualSocketClient` construction's handlers object literal (the one starting `new VisualSocketClient(wsUrl, { onSnapshot: ... })` around line 769), alongside the other `onX` entries such as `onOrgInfo`:

```tsx
      onGetLlmConfig: (payload) => {
        setLlmConfig(payload)
      },
      onUpdateLlmConfig: (payload) => {
        if (payload.ok) {
          setLlmConfig({
            default_model: payload.default_model ?? '',
            api_base: payload.api_base ?? '',
            api_key_set: Boolean(payload.api_key_set),
          })
          setLlmConfigSaveMessage('Saved')
        } else {
          setLlmConfigSaveMessage(payload.error || 'Save failed')
        }
      },
```

Insert `<IdentityMenu ... />` into `rail-bottom`, as the first child (before the "使用手册" button), following the exact same `clientRef.current?.method()` calling convention already used for `OrgTab`'s `onRequestData`/etc. props:

```tsx
<div className="rail-bottom">
  <IdentityMenu
    llmConfig={llmConfig}
    onRequestLlmConfig={() => clientRef.current?.getLlmConfig()}
    onSaveLlmConfig={(patch) => clientRef.current?.updateLlmConfig(patch)}
    saveMessage={llmConfigSaveMessage}
  />
  <button className={`rail-btn${showHelp ? ' active' : ''}`} onClick={() => setShowHelp((v) => !v)} title="使用手册">
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
Expected: PASS, prints `IdentityMenu.test.tsx passed`

Run the existing `App.test.tsx` suite for regressions:

Run: `npx tsx --test opc/plugins/office_ui/frontend_src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/IdentityMenu.tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx opc/plugins/office_ui/frontend_src/auth/identityMenu.css opc/plugins/office_ui/frontend_src/App.tsx
git commit -m "feat: add identity menu with settings entry to rail-bottom"
```

---

## Task 12: `NodesService` — read-only `sky status` snapshot

**Files:**
- Create: `opc/plugins/office_ui/services/nodes.py`
- Modify: `opc/plugins/office_ui/services/__init__.py`
- Test: `tests/test_nodes_service.py` (new)

**Interfaces:**
- Produces: `NodesService.list_nodes() -> ServiceResult` (payload: `{"available": bool, "clusters": [{"name", "status", "region", "instance_type", "price_per_hour", "runtime_seconds"}]}`; `available=False` with an empty `clusters` list when the `sky` binary is missing or the subprocess fails/returns invalid JSON).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nodes_service.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_nodes_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.services.nodes'`

- [ ] **Step 3: Implement**

Create `opc/plugins/office_ui/services/nodes.py`:

```python
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
```

In `opc/plugins/office_ui/services/__init__.py`, add the import and wire it into `OfficeServices.__init__` — note `NodesService()` takes no `context` (it has no dependency on project/engine state, unlike every other service):

```python
from .nodes import NodesService
```

```python
        self.nodes = NodesService()
```

```python
    "NodesService",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_nodes_service.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/services/nodes.py opc/plugins/office_ui/services/__init__.py tests/test_nodes_service.py
git commit -m "feat: add NodesService for read-only sky status snapshot"
```

---

## Task 13: WS wiring for `list_nodes`

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Modify: `docs/FRONTEND_BACKEND_MAP.md`
- Test: `opc/plugins/office_ui/tests/test_nodes_ws.py` (new)

**Interfaces:**
- Consumes: `NodesService.list_nodes` (Task 12).
- Produces: WS request type `list_nodes` (no payload), replying via `ack` with the `NodesService.list_nodes()` payload.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_nodes_ws.py`:

```python
"""WS-level test for list_nodes."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler() -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.agent_store = MagicMock()
    handler.chat_store = MagicMock()
    handler.event_adapter = MagicMock()
    handler._user_store = None
    handler._exec_mode = "task"
    handler._company_profile = "corporate"
    handler._task_preferred_agent = "native"
    return handler


class NodesWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_nodes_acks_unavailable_when_sky_missing(self) -> None:
        handler = _make_handler()
        ws = AsyncMock()
        with patch("shutil.which", return_value=None):
            await handler._handle_list_nodes(ws, {})
        sent = ws.send_json.await_args.args[0]
        self.assertFalse(sent["payload"]["available"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_nodes_ws.py -v`
Expected: FAIL with `AttributeError: 'WSHandler' object has no attribute '_handle_list_nodes'`

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/ws_handler.py`, add the handler near `_handle_get_llm_config` (Task 6):

```python
    async def _handle_list_nodes(self, ws: Any, data: dict) -> None:
        result = await self._ensure_office_services().nodes.list_nodes()
        await self._send_ack(ws, ok=True, **result.payload)
```

Register it in `_HANDLERS`:

```python
        "list_nodes":          _handle_list_nodes,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_nodes_ws.py -v`
Expected: PASS

- [ ] **Step 5: Document in FRONTEND_BACKEND_MAP.md**

Add a new section after the settings section from Task 6:

```markdown
## 十九、Nodes（SkyPilot 集群状态，只读）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 刷新集群状态 | NodesPanel | `list_nodes` | `_handle_list_nodes` | `nodes.list_nodes` | `ack` |
```

- [ ] **Step 6: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py opc/plugins/office_ui/tests/test_nodes_ws.py docs/FRONTEND_BACKEND_MAP.md
git commit -m "feat: wire list_nodes WS request type"
```

---

## Task 14: Frontend `NodesPanel` + rail-nav entry

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/nodes/NodesPanel.tsx`
- Create: `opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`
- Create: `opc/plugins/office_ui/frontend_src/nodes/nodes.css`
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx`

**Interfaces:**
- Consumes: a new `wsClient.listNodes(): void` + `onListNodes?: (payload: { available: boolean; clusters: Array<{...}> }) => void` (added in this task, same pattern as Task 9) — wired once inside `App.tsx`'s `VisualSocketClient` handlers object, per the established convention (Task 11 already established this: no child component touches `wsClient` directly).
- Produces: `NodesPanel({ nodes, onRefresh }: { nodes: { available: boolean; clusters: NodeCluster[] } | null; onRefresh: () => void })`; a new `'nodes'` member on `AppPage`; a "Nodes" button in `rail-nav`.

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`:

```tsx
// Source-text regex test, same convention as LoginScreen.test.tsx.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'NodesPanel.tsx'), 'utf-8')

assert.match(source, /onRefresh\(\)/, 'NodesPanel must call onRefresh to reload')
assert.match(source, /未检测到本机 SkyPilot|not detected/i, 'NodesPanel must render an unavailable message')
assert.doesNotMatch(source, /sky (start|stop|launch)/, 'NodesPanel must stay read-only — no start/stop/launch actions')
assert.doesNotMatch(source, /VisualSocketClient/, 'NodesPanel must stay presentational — no direct wsClient dependency')

console.log('NodesPanel.test.tsx passed')
```

Add a regex assertion to the end of `App.test.tsx` (append, do not remove existing assertions):

```tsx
assert.match(src, /'nodes'/, 'AppPage union must include the nodes page')
assert.match(src, /activePage === 'nodes'/, 'App must render NodesPanel when activePage is nodes')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx tsx opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`
Expected: FAIL — `ENOENT` reading `NodesPanel.tsx`

Run: `npx tsx --test opc/plugins/office_ui/frontend_src/App.test.tsx`
Expected: FAIL on the two new assertions just appended

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`, add to `SocketHandlers`:

```ts
  onListNodes?: (payload: { available: boolean; clusters: Array<{ name: string; status: string; region: string; instance_type: string; price_per_hour: number | null; runtime_seconds: number | null }> }) => void
```

Add the send method:

```ts
  listNodes(): void {
    this.send({ type: 'list_nodes' })
  }
```

Add the dispatch case:

```ts
    case 'list_nodes':
      this.handlers.onListNodes?.(parsed.payload as { available: boolean; clusters: any[] })
      break
```

Create `opc/plugins/office_ui/frontend_src/nodes/nodes.css`:

```css
.nodes-page {
  padding: 24px;
  overflow-y: auto;
}

.nodes-empty {
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 16px;
}

.nodes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.nodes-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 14px;
}

.nodes-card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.nodes-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.nodes-status-dot[data-status="UP"] { background: var(--green); }
.nodes-status-dot[data-status="INIT"] { background: var(--yellow); }
.nodes-status-dot[data-status="STOPPED"] { background: var(--text-dim); }

.nodes-card-detail {
  font-size: 12px;
  color: var(--text-secondary);
}
```

Create `opc/plugins/office_ui/frontend_src/nodes/NodesPanel.tsx`:

```tsx
import './nodes.css'

export interface NodeCluster {
  name: string
  status: string
  region: string
  instance_type: string
  price_per_hour: number | null
  runtime_seconds: number | null
}

interface NodesPanelProps {
  nodes: { available: boolean; clusters: NodeCluster[] } | null
  onRefresh: () => void
}

export function NodesPanel({ nodes, onRefresh }: NodesPanelProps) {
  return (
    <div className="nodes-page">
      <button type="button" onClick={onRefresh}>刷新</button>
      {!nodes ? null : !nodes.available ? (
        <div className="nodes-empty">未检测到本机 SkyPilot</div>
      ) : nodes.clusters.length === 0 ? (
        <div className="nodes-empty">No clusters</div>
      ) : (
        <div className="nodes-grid">
          {nodes.clusters.map(cluster => (
            <div className="nodes-card" key={cluster.name}>
              <div className="nodes-card-header">
                <span className="nodes-status-dot" data-status={cluster.status} />
                <strong>{cluster.name}</strong>
              </div>
              <div className="nodes-card-detail">{cluster.region} · {cluster.instance_type}</div>
              {cluster.price_per_hour != null && <div className="nodes-card-detail">${cluster.price_per_hour}/hr</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

In `opc/plugins/office_ui/frontend_src/App.tsx`:

Add `'nodes'` to the `AppPage` union (line 72):

```tsx
type AppPage = 'office' | 'workspace' | 'org' | 'mapEditor' | 'nodes'
```

Add the import:

```tsx
import { NodesPanel } from './nodes/NodesPanel'
```

Add state for the nodes snapshot, next to `llmConfig` (Task 11):

```tsx
const [nodesData, setNodesData] = useState<{ available: boolean; clusters: NodeCluster[] } | null>(null)
```

(This needs `import type { NodeCluster } from './nodes/NodesPanel'` alongside the `NodesPanel` import.)

Add the handler to the `VisualSocketClient` construction's handlers object literal, alongside `onGetLlmConfig`/`onUpdateLlmConfig` from Task 11:

```tsx
      onListNodes: (payload) => {
        setNodesData(payload)
      },
```

Add a "Nodes" button to `rail-nav`, after the "Org" button:

```tsx
  <button className={`rail-btn${activePage === 'nodes' ? ' active' : ''}`} onClick={() => setActivePage('nodes')} title="Nodes">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
    <span className="rail-btn-label">Nodes</span>
  </button>
```

Add the page render, alongside the `org`/`mapEditor` conditional blocks:

```tsx
{activePage === 'nodes' && (
  <div className="nodes-page-wrap">
    <NodesPanel nodes={nodesData} onRefresh={() => clientRef.current?.listNodes()} />
  </div>
)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx tsx opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`
Expected: PASS, prints `NodesPanel.test.tsx passed`

Run: `npx tsx --test opc/plugins/office_ui/frontend_src/App.test.tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/nodes opc/plugins/office_ui/frontend_src/lib/wsClient.ts opc/plugins/office_ui/frontend_src/App.tsx opc/plugins/office_ui/frontend_src/App.test.tsx
git commit -m "feat: add read-only Nodes panel showing local SkyPilot cluster status"
```

---

## Task 15: Full-stack verification

**Files:** none (verification only, per the design spec's own test plan section)

**Interfaces:** none.

- [ ] **Step 1: Run the full backend suite**

Run: `python -m pytest tests/ opc/plugins/office_ui/tests/ -q`
Expected: PASS, zero failures, zero regressions from Tasks 1-13

- [ ] **Step 2: Run the full frontend test set touched by this plan**

Run: `cd opc/plugins/office_ui/frontend_src && npx tsx --test lib/auth.test.ts auth/LoginScreen.test.tsx auth/IdentityMenu.test.tsx auth/SettingsPanel.test.tsx nodes/NodesPanel.test.tsx lib/wsClient.test.ts App.test.tsx`
Expected: PASS

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in files touched by this plan (pre-existing unrelated errors in `components/`/`@/lib/utils` are out of scope)

- [ ] **Step 3: Rebuild and manually verify in a real browser**

Run: `opc ui --rebuild`

Manually walk through the design spec's test plan (`docs/superpowers/specs/2026-07-11-post-login-ux-and-tenant-isolation-design.md`, "测试计划" section):

1. Register two accounts (A and B) via the login screen.
2. As A, create a project, send a chat message, add a kanban task.
3. Log out, log in as B. Confirm B's project list does not show A's project, and confirm B cannot see A's chat/kanban data.
4. As B, open the identity menu (avatar in `rail-bottom`) — confirm the username shown is "B", not "A".
5. Open "模型 / API Key 设置" from the identity menu, enter a fake API key (e.g. `sk-test-fake`), save, confirm the toast shows success without a page reload.
6. Start a Task Mode native-agent chat — confirm no `Missing Anthropic API Key` error.
7. Start a Task Mode `claude_code` external-agent chat — confirm the resulting error output (if the fake key is rejected upstream) references having attempted authentication, i.e. the key was read and sent, not "missing".
8. Click "Nodes" in `rail-nav` — confirm it shows either real cluster cards or the "未检测到本机 SkyPilot" message, with no start/stop controls.

- [ ] **Step 4: Report residual known limitations**

Confirm these are true and acceptable (matching the design spec's own "已知限制"/non-goals, plus one added by this plan):

- `agent_store.py` Office visual state remains global/shared across users (spec's explicit exclusion).
- A brand-new account that owns zero projects will see the server's currently-active project's initial WS snapshot until it creates its own project (Task 4's documented residual gap) — acceptable because it has no owned data to leak into, and normal usage always starts with creating or being handed a project.
- Per-role/per-project LLM config is not implemented (spec's explicit non-goal — `LLMConfig` stays global).
