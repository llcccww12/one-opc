# toC 账号体系（注册/登录）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give OpenOPC a minimal username + invite-code account system (register, login, session token, WS auth) that produces a stable `user_id` — the anchor every later toC sub-system (Tenant VM lifecycle, `opc worker`, credential vault, dispatch integration) will key off.

**Architecture:** A new `UserStore` (mirrors the existing `AgentStore`/`ChatStore` sqlite-in-`ui_state.db` pattern) backs two new plain-HTTP POST routes (`/api/register`, `/api/login`) plus a token check inserted into `WSHandler.handle_ws`. A CLI command (`opc user create-invite`) seeds invite codes since there is no admin UI yet. On the frontend, a new pre-app gate (`Root.tsx`) renders a `LoginScreen` until a session token exists in `localStorage`, then mounts the existing `App` with the token appended to the WS URL.

**Tech Stack:** Python 3.10+, aiohttp (existing, un-declared soft dependency of `office_ui`), aiosqlite (existing hard dependency), stdlib `hashlib`/`secrets` for credential hashing (no new dependency). React 19 + TypeScript on the frontend, zero test framework (`tsx` + `node:assert/strict`), Typer for the CLI.

## Global Constraints

- Scope is **only** the account system: register, login, session token, WS auth gate. VM lifecycle, `opc worker`, credential vault, and dispatch/routing changes are separate follow-up plans — do not implement them here.
- Registration/login credentials are **username + invite code** only — no password field, no email, no OAuth/SSO (source: `docs/superpowers/specs/2026-07-11-saas-toc-skypilot-design.md`, "用户注册与登录（MVP）").
- Explicitly out of scope for this plan (per the spec's "这轮明确不做" list): password recovery, email verification, OAuth/SSO, an invite-code batch-management UI, invite-code single/multi-use policy beyond the simplest working default chosen below, session token expiry/revocation.
- No per-user path segments anywhere in `opc/core/config.py` — confirmed today there is zero `user_id` concept there, and this plan must not add one. `users`/`invite_codes`/`sessions` live only in `ui_state.db` (global, not per-project).
- **v1 invite-code semantics (this plan's own simplifying choice, not dictated by the spec):** an invite code is valid for registration exactly once — the first successful registration marks it `used` and binds it to that user's `password_hash`. Login re-uses the same code as the permanent credential. This satisfies "邀请码本身就是登录凭证" while punting the "一次性 vs 多次使用" open question forward, exactly as the spec allows.
- Follow existing repo conventions exactly: `UserStore` mirrors `AgentStore`/`ChatStore` (`initialize()` does `CREATE TABLE IF NOT EXISTS`); HTTP routes mirror the `_make_attachment_handler` factory-closure pattern in `server.py`; CLI commands mirror the `project_app`/`session_app` Typer sub-app pattern in `opc/cli/app.py`; Python tests mirror `opc/plugins/office_ui/tests/test_agent_store.py` (`unittest.IsolatedAsyncioTestCase` + in-memory `aiosqlite`) and `tests/test_ws_handler_escalations.py` (`object.__new__(WSHandler)` bypass-construction for isolated method tests); frontend tests mirror `lib/sessionRuntime.test.ts` (pure-function `node:assert` script, no DOM) and `App.test.tsx` (regex-over-source-text for components that can't be rendered under plain Node).
- `WSHandler.__init__` currently has ~40 call sites across the test suite with the existing 4-positional-argument signature. The new `user_store` parameter **must** be added as an optional 5th argument defaulting to `None` — never make it required — so none of those call sites need touching. When `user_store is None`, WS auth is skipped entirely (test-only escape hatch); the real server in `server.py` always passes a real `UserStore`, so production enforces auth unconditionally.

---

### Task 1: `UserStore` — accounts, invite codes, sessions

**Files:**
- Create: `opc/plugins/office_ui/user_store.py`
- Test: `opc/plugins/office_ui/tests/test_user_store.py`

**Interfaces:**
- Produces: `class UserStore` with `__init__(self, db: aiosqlite.Connection) -> None`, `async def initialize(self) -> None`, `async def create_invite_code(self, code: str) -> None`, `async def register(self, username: str, invite_code: str) -> tuple[str | None, str | None]` (returns `(user_id, None)` on success or `(None, error_code)` on failure, where `error_code` is one of `"invite_code_invalid"`, `"invite_code_used"`, `"username_taken"`), `async def authenticate(self, username: str, invite_code: str) -> str | None` (returns `user_id` or `None`), `async def create_session(self, user_id: str) -> str` (returns an opaque token), `async def get_user_id_for_token(self, token: str) -> str | None`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_user_store.py`:

```python
from __future__ import annotations

import unittest

import aiosqlite

from opc.plugins.office_ui.user_store import UserStore


class UserStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = UserStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_register_with_valid_invite_code_succeeds(self) -> None:
        await self.store.create_invite_code("CODE1")
        user_id, error = await self.store.register("alice", "CODE1")
        self.assertIsNone(error)
        self.assertIsNotNone(user_id)

    async def test_register_with_unknown_invite_code_fails(self) -> None:
        user_id, error = await self.store.register("alice", "BOGUS")
        self.assertIsNone(user_id)
        self.assertEqual(error, "invite_code_invalid")

    async def test_register_with_already_used_invite_code_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.register("alice", "CODE1")
        user_id, error = await self.store.register("bob", "CODE1")
        self.assertIsNone(user_id)
        self.assertEqual(error, "invite_code_used")

    async def test_register_with_duplicate_username_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.create_invite_code("CODE2")
        await self.store.register("alice", "CODE1")
        user_id, error = await self.store.register("alice", "CODE2")
        self.assertIsNone(user_id)
        self.assertEqual(error, "username_taken")

    async def test_authenticate_with_correct_credentials_succeeds(self) -> None:
        await self.store.create_invite_code("CODE1")
        registered_id, _ = await self.store.register("alice", "CODE1")
        user_id = await self.store.authenticate("alice", "CODE1")
        self.assertEqual(user_id, registered_id)

    async def test_authenticate_with_wrong_invite_code_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.register("alice", "CODE1")
        user_id = await self.store.authenticate("alice", "WRONG")
        self.assertIsNone(user_id)

    async def test_authenticate_unknown_username_fails(self) -> None:
        user_id = await self.store.authenticate("nobody", "CODE1")
        self.assertIsNone(user_id)

    async def test_session_token_round_trip(self) -> None:
        await self.store.create_invite_code("CODE1")
        registered_id, _ = await self.store.register("alice", "CODE1")
        token = await self.store.create_session(registered_id)
        resolved_id = await self.store.get_user_id_for_token(token)
        self.assertEqual(resolved_id, registered_id)

    async def test_unknown_token_resolves_to_none(self) -> None:
        resolved_id = await self.store.get_user_id_for_token("bogus-token")
        self.assertIsNone(resolved_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_user_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.user_store'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/user_store.py`:

```python
"""SQLite-backed store for user accounts, invite codes, and session tokens.

Mirrors the AgentStore/ChatStore pattern: the connection is opened once by
the caller (server.py or a CLI command) and shared; initialize() only ever
CREATEs, never migrates existing installs (there are none yet).
"""

from __future__ import annotations

import hashlib
import secrets
import time

import aiosqlite


def _hash_invite_code(invite_code: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", invite_code.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex()


class UserStore:
    """Persists users, invite codes, and session tokens in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'unused',
                used_by_user_id TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def create_invite_code(self, code: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO invite_codes (code, status, created_at) VALUES (?, 'unused', ?)",
            (code, time.time()),
        )
        await self._db.commit()

    async def register(self, username: str, invite_code: str) -> tuple[str | None, str | None]:
        """Create a user account. Returns (user_id, None) or (None, error_code)."""
        cursor = await self._db.execute(
            "SELECT status FROM invite_codes WHERE code = ?", (invite_code,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None, "invite_code_invalid"
        if row[0] != "unused":
            return None, "invite_code_used"

        cursor = await self._db.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if await cursor.fetchone() is not None:
            return None, "username_taken"

        user_id = secrets.token_hex(16)
        salt = secrets.token_hex(16)
        password_hash = _hash_invite_code(invite_code, salt)
        await self._db.execute(
            "INSERT INTO users (user_id, username, password_salt, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, salt, password_hash, time.time()),
        )
        await self._db.execute(
            "UPDATE invite_codes SET status = 'used', used_by_user_id = ? WHERE code = ?",
            (user_id, invite_code),
        )
        await self._db.commit()
        return user_id, None

    async def authenticate(self, username: str, invite_code: str) -> str | None:
        """Verify username + invite_code. Returns user_id on success, None on failure."""
        cursor = await self._db.execute(
            "SELECT user_id, password_salt, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        user_id, salt, expected_hash = row
        if _hash_invite_code(invite_code, salt) != expected_hash:
            return None
        return user_id

    async def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        await self._db.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, time.time()),
        )
        await self._db.commit()
        return token

    async def get_user_id_for_token(self, token: str) -> str | None:
        cursor = await self._db.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        row = await cursor.fetchone()
        return row[0] if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_user_store.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/user_store.py opc/plugins/office_ui/tests/test_user_store.py
git commit -m "feat: add UserStore for account/invite-code/session persistence"
```

---

### Task 2: `opc user create-invite` CLI command

**Files:**
- Modify: `opc/cli/app.py` (add a new `user_app` Typer sub-app near the other `*_app` groups, e.g. right before `session_app = typer.Typer(...)` at line 1747)
- Test: `tests/test_cli_app.py` (add a new test class)

**Interfaces:**
- Consumes: `UserStore.__init__(db)`, `UserStore.initialize()`, `UserStore.create_invite_code(code)` from Task 1.
- Produces: CLI command `opc user create-invite [CODE]` — writes a row into `ui_state.db`'s `invite_codes` table, printing the code (generated if omitted).

**Design note:** unlike `project_app`/`session_app`, this command does **not** go through `OfficeServiceFactory` — that factory boots the entire `OPCEngine` (all seven layers) just to reach `ui_state.db`, which is disproportionate for a one-line admin seeding utility. Instead it opens `ui_state.db` directly via `aiosqlite`, the same way `server.py`'s `create_app` does, using `get_opc_home()` (already imported at the top of `opc/cli/app.py`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_app.py` (new class, place it after `class CliTalentCommandTests` around line 3080, before `class CliBoardCommandTests`):

```python
class CliUserCommandTests(unittest.TestCase):
    def test_create_invite_seeds_ui_state_db(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            opc_home = Path(tmpdir) / ".opc"
            with patch("opc.cli.app.get_opc_home", return_value=opc_home):
                result = runner.invoke(app, ["user", "create-invite", "TESTCODE1"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("TESTCODE1", result.output)

            conn = sqlite3.connect(str(opc_home / "ui_state.db"))
            try:
                row = conn.execute(
                    "SELECT status FROM invite_codes WHERE code = ?", ("TESTCODE1",)
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "unused")

    def test_create_invite_without_code_generates_one(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            opc_home = Path(tmpdir) / ".opc"
            with patch("opc.cli.app.get_opc_home", return_value=opc_home):
                result = runner.invoke(app, ["user", "create-invite"])

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Invite code created", result.output)
```

(`sqlite3`, `tempfile`, `Path`, `patch`, `CliRunner`, `app` are already imported at the top of this file — no new imports needed.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_app.py::CliUserCommandTests -v`
Expected: FAIL with `RuntimeError: No such command 'user'` (or non-zero `result.exit_code` with "No such command" in `result.output`)

- [ ] **Step 3: Write the implementation**

In `opc/cli/app.py`, insert immediately before the line `session_app = typer.Typer(help="Manage OPC sessions")` (currently line 1747):

```python
user_app = typer.Typer(help="Manage OpenOPC user accounts (invite codes)")
app.add_typer(user_app, name="user")


@user_app.command("create-invite")
def user_create_invite(
    code: Optional[str] = typer.Argument(None, help="Invite code to create; a random one is generated if omitted"),
    json_output: bool = typer.Option(False, "--json", help="Print JSON"),
):
    """Create an invite code that a new user can register with."""
    import secrets as _secrets

    import aiosqlite

    from opc.plugins.office_ui.user_store import UserStore

    invite_code = code or _secrets.token_hex(4).upper()

    async def _create() -> None:
        opc_home = get_opc_home()
        opc_home.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(opc_home / "ui_state.db"))
        try:
            await db.execute("PRAGMA busy_timeout=30000")
            store = UserStore(db)
            await store.initialize()
            await store.create_invite_code(invite_code)
        finally:
            await db.close()

    asyncio.run(_create())
    payload = {"ok": True, "invite_code": invite_code}
    if json_output:
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console.print(f"Invite code created: [success]{invite_code}[/success]")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_app.py::CliUserCommandTests -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/cli/app.py tests/test_cli_app.py
git commit -m "feat: add 'opc user create-invite' CLI command"
```

---

### Task 3: `/api/register` and `/api/login` HTTP routes

**Files:**
- Create: `opc/plugins/office_ui/auth_routes.py`
- Test: `opc/plugins/office_ui/tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `UserStore` from Task 1 (`register`, `authenticate`, `create_session`).
- Produces: `make_register_handler(user_store: UserStore) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]` and `make_login_handler(user_store: UserStore) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.Response]]`. Both handlers accept a JSON body `{"username": str, "invite_code": str}` and respond `{"ok": true, "token": str, "user_id": str}` (HTTP 200) or `{"ok": false, "error": str}` (HTTP 400/401).

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/tests/test_auth_routes.py`:

```python
from __future__ import annotations

import unittest

import aiosqlite
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from opc.plugins.office_ui.auth_routes import make_login_handler, make_register_handler
from opc.plugins.office_ui.user_store import UserStore


class AuthRoutesTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.db = await aiosqlite.connect(":memory:")
        self.user_store = UserStore(self.db)
        await self.user_store.initialize()
        await self.user_store.create_invite_code("INVITE1")
        app = web.Application()
        app.router.add_post("/api/register", make_register_handler(self.user_store))
        app.router.add_post("/api/login", make_login_handler(self.user_store))
        return app

    async def tearDownAsync(self) -> None:
        await self.db.close()
        await super().tearDownAsync()

    async def test_register_then_login_succeeds(self) -> None:
        resp = await self.client.post(
            "/api/register", json={"username": "alice", "invite_code": "INVITE1"}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("token", data)

        resp2 = await self.client.post(
            "/api/login", json={"username": "alice", "invite_code": "INVITE1"}
        )
        self.assertEqual(resp2.status, 200)
        data2 = await resp2.json()
        self.assertTrue(data2["ok"])
        self.assertIn("token", data2)

    async def test_register_with_invalid_invite_code_returns_400(self) -> None:
        resp = await self.client.post(
            "/api/register", json={"username": "bob", "invite_code": "BOGUS"}
        )
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertFalse(data["ok"])

    async def test_register_with_used_invite_code_returns_400(self) -> None:
        await self.client.post(
            "/api/register", json={"username": "carol", "invite_code": "INVITE1"}
        )
        resp = await self.client.post(
            "/api/register", json={"username": "dave", "invite_code": "INVITE1"}
        )
        self.assertEqual(resp.status, 400)

    async def test_login_with_wrong_invite_code_returns_401(self) -> None:
        await self.client.post(
            "/api/register", json={"username": "erin", "invite_code": "INVITE1"}
        )
        resp = await self.client.post(
            "/api/login", json={"username": "erin", "invite_code": "WRONG"}
        )
        self.assertEqual(resp.status, 401)

    async def test_register_with_missing_fields_returns_400(self) -> None:
        resp = await self.client.post("/api/register", json={"username": "frank"})
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest opc/plugins/office_ui/tests/test_auth_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.auth_routes'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/auth_routes.py`:

```python
"""HTTP handlers for user registration and login (POST /api/register, /api/login)."""

from __future__ import annotations

import aiohttp.web

from opc.plugins.office_ui.user_store import UserStore


async def _parse_credentials(request: aiohttp.web.Request) -> tuple[str, str] | aiohttp.web.Response:
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    username = str(body.get("username") or "").strip()
    invite_code = str(body.get("invite_code") or "").strip()
    if not username or not invite_code:
        return aiohttp.web.json_response({"ok": False, "error": "missing_fields"}, status=400)
    return username, invite_code


def make_register_handler(user_store: UserStore):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        parsed = await _parse_credentials(request)
        if isinstance(parsed, aiohttp.web.Response):
            return parsed
        username, invite_code = parsed
        user_id, error = await user_store.register(username, invite_code)
        if error is not None:
            return aiohttp.web.json_response({"ok": False, "error": error}, status=400)
        token = await user_store.create_session(user_id)
        return aiohttp.web.json_response({"ok": True, "token": token, "user_id": user_id})

    return _handle


def make_login_handler(user_store: UserStore):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        parsed = await _parse_credentials(request)
        if isinstance(parsed, aiohttp.web.Response):
            return parsed
        username, invite_code = parsed
        user_id = await user_store.authenticate(username, invite_code)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "invalid_credentials"}, status=401)
        token = await user_store.create_session(user_id)
        return aiohttp.web.json_response({"ok": True, "token": token, "user_id": user_id})

    return _handle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest opc/plugins/office_ui/tests/test_auth_routes.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/auth_routes.py opc/plugins/office_ui/tests/test_auth_routes.py
git commit -m "feat: add /api/register and /api/login HTTP routes"
```

---

### Task 4: Wire `UserStore` and auth routes into `server.py`

**Files:**
- Modify: `opc/plugins/office_ui/server.py`

**Interfaces:**
- Consumes: `UserStore` (Task 1), `make_register_handler`/`make_login_handler` (Task 3).
- Produces: `app["user_store"]` available on the running `aiohttp.web.Application`; `/api/register` and `/api/login` reachable on the real server.

**Why this task has no dedicated new automated test:** `create_app()` unconditionally constructs a real `OPCEngine` and calls `await engine.initialize()`, which boots all seven OPC layers — there is no lighter seam to inject a fake engine just to assert two `add_post` calls happened. `opc/plugins/office_ui/tests/test_server_paths.py` deliberately stays scoped to pure-function tests of `_is_under_path` and doesn't boot `create_app()` at all; extending it with a full engine-boot test would be disproportionate to what this task changes (two route registrations + one constructor argument). The change is still covered twice over: Task 4 Step 2 below re-runs the full existing regression suite (which constructs real `WSHandler`/`ChatStore`/`AgentStore` objects and would fail on a signature/import mistake), and Task 9's manual walkthrough exercises `/api/register` and `/api/login` against the real running server end-to-end — which is the only thing a synthetic route-registration test could have told us anyway.

- [ ] **Step 1: Write the implementation**

In `opc/plugins/office_ui/server.py`:

Add imports after the existing `from opc.plugins.office_ui.chat_store import ChatStore` line:

```python
from opc.plugins.office_ui.auth_routes import make_login_handler, make_register_handler
from opc.plugins.office_ui.user_store import UserStore
```

After the existing block:

```python
    chat_store = ChatStore(db)
    await chat_store.initialize()
```

insert:

```python

    user_store = UserStore(db)
    await user_store.initialize()
```

Change the `WSHandler` construction line from:

```python
    ws_handler = WSHandler(engine, agent_store, chat_store, event_adapter)
```

to:

```python
    ws_handler = WSHandler(engine, agent_store, chat_store, event_adapter, user_store)
```

In the "Store references for cleanup" block, add `app["user_store"] = user_store` alongside the existing `app["engine"] = engine` line.

In the "Routes" block, insert the new routes right after the existing attachment-download route and before the `# SPA:` comment:

```python
    # Account registration/login (must be registered before the SPA catch-all)
    app.router.add_post("/api/register", make_register_handler(user_store))
    app.router.add_post("/api/login", make_login_handler(user_store))
```

- [ ] **Step 2: Run the existing regression suite**

Run: `python -m pytest opc/plugins/office_ui/tests/ -v`
Expected: all PASS — confirms the `WSHandler(engine, agent_store, chat_store, event_adapter, user_store)` constructor call and the new imports didn't break anything already covered.

- [ ] **Step 3: Commit**

```bash
git add opc/plugins/office_ui/server.py
git commit -m "feat: wire UserStore and /api/register, /api/login into the office-UI server"
```

---

### Task 5: Token-authenticated WebSocket connections

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Test: `tests/test_ws_handler_auth.py` (new file, repo-root `tests/` — mirrors `tests/test_ws_handler_escalations.py`'s bypass-construction style)

**Interfaces:**
- Consumes: `UserStore.get_user_id_for_token(token)` from Task 1.
- Produces: `WSHandler.__init__(self, engine, agent_store, chat_store, event_adapter, user_store=None)` (new 5th optional parameter); `async def WSHandler._authenticate_ws_request(self, request) -> str | None` (new method: resolves a `user_id` from `request.query["token"]`, or returns `"anonymous"` unconditionally when `self._user_store is None`, or `None` to signal "reject this connection").

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_handler_auth.py`:

```python
"""Unit tests for WSHandler's token-based WS authentication hook."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from opc.plugins.office_ui.ws_handler import WSHandler


class _FakeRequest:
    def __init__(self, token: str | None) -> None:
        self.query = {"token": token} if token is not None else {}


class WSHandlerAuthTests(unittest.IsolatedAsyncioTestCase):
    def _make_handler(self, user_store) -> WSHandler:
        handler = object.__new__(WSHandler)
        handler._user_store = user_store
        return handler

    async def test_no_user_store_allows_connection(self) -> None:
        handler = self._make_handler(None)
        user_id = await handler._authenticate_ws_request(_FakeRequest(None))
        self.assertEqual(user_id, "anonymous")

    async def test_missing_token_is_rejected(self) -> None:
        handler = self._make_handler(AsyncMock())
        user_id = await handler._authenticate_ws_request(_FakeRequest(None))
        self.assertIsNone(user_id)

    async def test_valid_token_resolves_user_id(self) -> None:
        store = AsyncMock()
        store.get_user_id_for_token.return_value = "user-123"
        handler = self._make_handler(store)
        user_id = await handler._authenticate_ws_request(_FakeRequest("tok"))
        self.assertEqual(user_id, "user-123")
        store.get_user_id_for_token.assert_awaited_once_with("tok")

    async def test_invalid_token_is_rejected(self) -> None:
        store = AsyncMock()
        store.get_user_id_for_token.return_value = None
        handler = self._make_handler(store)
        user_id = await handler._authenticate_ws_request(_FakeRequest("bad"))
        self.assertIsNone(user_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ws_handler_auth.py -v`
Expected: FAIL with `AttributeError: 'WSHandler' object has no attribute '_authenticate_ws_request'`

- [ ] **Step 3: Write the implementation**

In `opc/plugins/office_ui/ws_handler.py`, add `UserStore` to the existing `TYPE_CHECKING` import block:

```python
if TYPE_CHECKING:
    import aiohttp.web
    from opc.engine import OPCEngine
    from opc.plugins.office_ui.agent_store import AgentStore
    from opc.plugins.office_ui.chat_store import ChatStore
    from opc.plugins.office_ui.event_adapter import EventAdapter
    from opc.plugins.office_ui.user_store import UserStore
```

Change the `__init__` signature from:

```python
    def __init__(
        self,
        engine: OPCEngine,
        agent_store: AgentStore,
        chat_store: ChatStore,
        event_adapter: EventAdapter,
    ) -> None:
```

to:

```python
    def __init__(
        self,
        engine: OPCEngine,
        agent_store: AgentStore,
        chat_store: ChatStore,
        event_adapter: EventAdapter,
        user_store: UserStore | None = None,
    ) -> None:
```

Right after the existing `self.event_adapter = event_adapter` line, add:

```python
        self._user_store = user_store
        self._client_user_ids: dict[Any, str] = {}
```

Add a new method near `handle_ws` (e.g. immediately before it):

```python
    async def _authenticate_ws_request(self, request: Any) -> str | None:
        """Resolve the user_id for an inbound WS connection, or None to reject it.

        When no user_store is configured (the common case in unit tests that
        construct WSHandler directly), auth is skipped entirely — only the
        real office-UI server wires a UserStore, so production always enforces
        this check.
        """
        if self._user_store is None:
            return "anonymous"
        token = request.query.get("token")
        if not token:
            return None
        return await self._user_store.get_user_id_for_token(token)
```

In `handle_ws`, change:

```python
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if self._shutting_down:
            await ws.close()
            return ws
        self._clients.add(ws)
```

to:

```python
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        user_id = await self._authenticate_ws_request(request)
        if user_id is None:
            await ws.close(code=4401, message=b"unauthorized")
            return ws
        self._client_user_ids[ws] = user_id
        if self._shutting_down:
            await ws.close()
            return ws
        self._clients.add(ws)
```

In the `finally:` cleanup block of `handle_ws`, change:

```python
        finally:
            self._clients.discard(ws)
            try:
                self._client_project_ids.pop(ws, None)
```

to:

```python
        finally:
            self._clients.discard(ws)
            self._client_user_ids.pop(ws, None)
            try:
                self._client_project_ids.pop(ws, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ws_handler_auth.py -v`
Expected: PASS (4 tests)

Then run the broader WS handler test files to confirm the optional `user_store` parameter didn't break any of the ~40 existing 4-positional-argument call sites:

Run: `python -m pytest tests/test_ws_handler_escalations.py tests/test_ws_handler_progress_parsing.py tests/test_session_integration.py tests/test_parallel_runtime_isolation.py tests/test_attachment_multimodal_routing.py tests/test_reply_projection_invariant.py tests/test_company_recruiter.py opc/plugins/office_ui/tests/test_org_info_payload.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py tests/test_ws_handler_auth.py
git commit -m "feat: authenticate WebSocket connections with a per-user session token"
```

---

### Task 6: Frontend `lib/auth.ts` — session storage + register/login calls

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/lib/auth.ts`
- Test: `opc/plugins/office_ui/frontend_src/lib/auth.test.ts`

**Interfaces:**
- Produces: `getStoredToken(): string | null`, `getStoredUsername(): string | null`, `storeSession(token: string, username: string): void`, `clearSession(): void`, `validateCredentials(username: string, inviteCode: string): string | null` (returns a Chinese error message, or `null` if valid), `register(username: string, inviteCode: string): Promise<AuthResult>`, `login(username: string, inviteCode: string): Promise<AuthResult>`, where `interface AuthResult { ok: boolean; token?: string; error?: string }`.

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/lib/auth.test.ts`:

```ts
// Runs with `tsx` against node:assert/strict — matches repo convention for
// zero-framework tests. Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/auth.test.ts`
import assert from 'node:assert/strict'
import { validateCredentials, register, login } from './auth'

assert.equal(validateCredentials('', 'code'), '请输入用户名')
assert.equal(validateCredentials('alice', ''), '请输入邀请码')
assert.equal(validateCredentials('alice', 'code'), null)

async function run(): Promise<void> {
  let capturedUrl = ''
  let capturedBody = ''
  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedBody = init.body as string
    return {
      ok: true,
      json: async () => ({ ok: true, token: 'tok123' }),
    }
  }
  const result = await register('alice', 'invite1')
  assert.equal(capturedUrl, '/api/register')
  assert.deepEqual(JSON.parse(capturedBody), { username: 'alice', invite_code: 'invite1' })
  assert.equal(result.ok, true)
  assert.equal(result.token, 'tok123')

  ;(globalThis as any).fetch = async () => ({
    ok: false,
    json: async () => ({ ok: false, error: 'bad code' }),
  })
  const failed = await login('alice', 'wrong')
  assert.equal(failed.ok, false)
  assert.equal(failed.error, 'bad code')

  console.log('auth.test.ts passed')
}

run()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/auth.test.ts`
Expected: FAIL — `Cannot find module './auth'`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/frontend_src/lib/auth.ts`:

```ts
const TOKEN_KEY = 'opc_session_token'
const USERNAME_KEY = 'opc_username'

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function getStoredUsername(): string | null {
  return window.localStorage.getItem(USERNAME_KEY)
}

export function storeSession(token: string, username: string): void {
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(USERNAME_KEY, username)
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USERNAME_KEY)
}

export function validateCredentials(username: string, inviteCode: string): string | null {
  if (!username.trim()) return '请输入用户名'
  if (!inviteCode.trim()) return '请输入邀请码'
  return null
}

export interface AuthResult {
  ok: boolean
  token?: string
  error?: string
}

async function postAuth(path: string, username: string, inviteCode: string): Promise<AuthResult> {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, invite_code: inviteCode }),
    })
    const data = await res.json()
    if (!res.ok || !data.ok) {
      return { ok: false, error: data.error ?? '请求失败' }
    }
    return { ok: true, token: data.token }
  } catch {
    return { ok: false, error: '网络错误' }
  }
}

export function register(username: string, inviteCode: string): Promise<AuthResult> {
  return postAuth('/api/register', username, inviteCode)
}

export function login(username: string, inviteCode: string): Promise<AuthResult> {
  return postAuth('/api/login', username, inviteCode)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/auth.test.ts`
Expected: `auth.test.ts passed` printed, exit code 0

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/lib/auth.ts opc/plugins/office_ui/frontend_src/lib/auth.test.ts
git commit -m "feat: add frontend session storage and register/login API calls"
```

---

### Task 7: `LoginScreen` + `Root` pre-app gate

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/auth/LoginScreen.tsx`
- Create: `opc/plugins/office_ui/frontend_src/auth/auth.css`
- Create: `opc/plugins/office_ui/frontend_src/auth/Root.tsx`
- Test: `opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/main.tsx`

**Interfaces:**
- Consumes: `getStoredToken`, `register`, `login`, `storeSession`, `validateCredentials` from `../lib/auth` (Task 6); the existing default-exported `App` component from `../App`.
- Produces: `export function LoginScreen({ onAuthenticated }: { onAuthenticated: () => void }): JSX.Element`; `export default function Root(): JSX.Element` (renders `LoginScreen` until a token is stored, then `App`).

- [ ] **Step 1: Write the failing test**

Create `opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`:

```ts
// Source-text regex test — matches the App.test.tsx convention for
// components that reference browser globals and can't be rendered under
// plain Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'LoginScreen.tsx'), 'utf-8')

assert.match(source, /login\(username, inviteCode\)/, 'LoginScreen must call login() in login mode')
assert.match(source, /register\(username, inviteCode\)/, 'LoginScreen must call register() in register mode')
assert.match(source, /storeSession\(/, 'LoginScreen must persist the session token on success')
assert.match(source, /validateCredentials\(/, 'LoginScreen must validate input before submitting')
assert.match(source, /onAuthenticated\(\)/, 'LoginScreen must notify its parent once authenticated')

console.log('LoginScreen.test.tsx passed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`
Expected: FAIL — `ENOENT: no such file or directory ... LoginScreen.tsx`

- [ ] **Step 3: Write the implementation**

Create `opc/plugins/office_ui/frontend_src/auth/LoginScreen.tsx`:

```tsx
import { useState, type FormEvent } from 'react'
import { login, register, storeSession, validateCredentials } from '../lib/auth'
import './auth.css'

interface LoginScreenProps {
  onAuthenticated: () => void
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const validationError = validateCredentials(username, inviteCode)
    if (validationError) {
      setError(validationError)
      return
    }
    setSubmitting(true)
    setError(null)
    const result = mode === 'login' ? await login(username, inviteCode) : await register(username, inviteCode)
    setSubmitting(false)
    if (!result.ok || !result.token) {
      setError(result.error ?? (mode === 'login' ? '登录失败' : '注册失败'))
      return
    }
    storeSession(result.token, username)
    onAuthenticated()
  }

  return (
    <div className="app-shell auth-screen">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>{mode === 'login' ? '登录' : '注册'}</h1>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="用户名"
          autoComplete="username"
        />
        <input
          value={inviteCode}
          onChange={(e) => setInviteCode(e.target.value)}
          placeholder="邀请码"
          type="password"
          autoComplete="off"
        />
        {error && <div className="auth-error">{error}</div>}
        <button type="submit" disabled={submitting}>
          {submitting ? '处理中...' : mode === 'login' ? '登录' : '注册'}
        </button>
        <button
          type="button"
          className="auth-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
        >
          {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
        </button>
      </form>
    </div>
  )
}
```

Create `opc/plugins/office_ui/frontend_src/auth/auth.css`:

```css
.auth-screen {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 320px;
  padding: 32px;
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.auth-form h1 {
  margin: 0 0 8px;
  font-size: 20px;
  color: var(--text);
}

.auth-form input {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
  font-size: 14px;
}

.auth-form button[type='submit'] {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: none;
  background: var(--accent);
  color: var(--accent-foreground);
  font-size: 14px;
  cursor: pointer;
}

.auth-form button[type='submit']:disabled {
  opacity: 0.6;
  cursor: default;
}

.auth-switch {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  padding: 0;
}

.auth-error {
  color: #ef4444;
  font-size: 13px;
}
```

Create `opc/plugins/office_ui/frontend_src/auth/Root.tsx`:

```tsx
import { useState } from 'react'
import App from '../App'
import { LoginScreen } from './LoginScreen'
import { getStoredToken } from '../lib/auth'

export default function Root() {
  const [authenticated, setAuthenticated] = useState<boolean>(getStoredToken() !== null)
  if (!authenticated) {
    return <LoginScreen onAuthenticated={() => setAuthenticated(true)} />
  }
  return <App />
}
```

Modify `opc/plugins/office_ui/frontend_src/main.tsx`: change the import `import App from './App'` to `import Root from './auth/Root'`, and change the render call from:

```tsx
  createRoot(root).render(
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
```

to:

```tsx
  createRoot(root).render(
    <ErrorBoundary>
      <Root />
    </ErrorBoundary>
  )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`
Expected: `LoginScreen.test.tsx passed` printed, exit code 0

Then run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new type errors introduced by `LoginScreen.tsx`, `Root.tsx`, or `main.tsx` (pre-existing unrelated errors in `components/`/`@/lib/utils` are expected and not your concern here).

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/ opc/plugins/office_ui/frontend_src/main.tsx
git commit -m "feat: add LoginScreen + Root pre-app auth gate"
```

---

### Task 8: Attach the session token to the WebSocket connection

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`

**Interfaces:**
- Consumes: `getStoredToken`, `clearSession` from `./lib/auth` (Task 6).
- Produces: `defaultWsUrl()` now appends `?token=<token>` when a token is stored; `VisualSocketClient`'s `SocketHandlers` interface gains an optional `onAuthError?: () => void`, invoked when the server closes the connection with close code `4401` (the code Task 5 uses for "unauthorized").

- [ ] **Step 1: Write the failing test**

There is no existing test file covering `defaultWsUrl()` or `wsClient.ts`'s close-handling — this is UI wiring that's fastest and most reliably verified through the manual browser check in Task 9, not a new unit test (matching how the rest of `App.tsx`'s WS wiring is already untested at the unit level; only `App.test.tsx`'s structural regex assertions and the pure-function `lib/` tests exist as precedent, and neither targets this kind of imperative event-handler wiring).

Skip straight to Step 3; verification for this task is the `npm run typecheck` in Step 4 plus the end-to-end manual check in Task 9.

- [ ] **Step 2: (skipped — no unit test for this task, see Step 1)**

- [ ] **Step 3: Write the implementation**

In `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`, add `onAuthError?: () => void` to the `SocketHandlers` interface, right after the existing `onStatus?: (status: SocketStatus, detail?: string) => void` line:

```ts
  onStatus?: (status: SocketStatus, detail?: string) => void
  onAuthError?: () => void
```

Change the `onclose` handler from:

```ts
    this.ws.onclose = () => {
      this.stopHeartbeat()
      this.handlers.onStatus?.('disconnected')
      this.ws = null
      if (!this.closedByUser) {
        this.scheduleReconnect()
      }
    }
```

to:

```ts
    this.ws.onclose = (event) => {
      this.stopHeartbeat()
      this.handlers.onStatus?.('disconnected')
      this.ws = null
      if (event.code === 4401) {
        this.closedByUser = true
        this.handlers.onAuthError?.()
        return
      }
      if (!this.closedByUser) {
        this.scheduleReconnect()
      }
    }
```

In `opc/plugins/office_ui/frontend_src/App.tsx`, add an import right after the existing `import { VisualSocketClient } from './lib/wsClient'` line (line 4):

```tsx
import { getStoredToken, clearSession } from './lib/auth'
```

Change `defaultWsUrl()` (currently lines 74-77) from:

```tsx
function defaultWsUrl(): string {
  const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${wsProto}://${window.location.hostname}:${window.location.port || '8765'}/ws`
}
```

to:

```tsx
function defaultWsUrl(): string {
  const wsProto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = getStoredToken()
  const query = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${wsProto}://${window.location.hostname}:${window.location.port || '8765'}/ws${query}`
}
```

In the `VisualSocketClient` construction (the handlers object starting at `const client = new VisualSocketClient(wsUrl, { ... })`), add a new handler right after the existing `onStatus: (next, detail) => { ... },` block:

```tsx
      onAuthError: () => {
        clearSession()
        window.location.reload()
      },
```

- [ ] **Step 4: Run typecheck**

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new type errors introduced by these edits (pre-existing unrelated errors are expected).

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/App.tsx opc/plugins/office_ui/frontend_src/lib/wsClient.ts
git commit -m "feat: attach session token to the WS connection, handle server-side auth rejection"
```

---

### Task 9: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Build the frontend and start the server**

```bash
cd opc/plugins/office_ui/frontend_src && npm install && npm run build
cd /Users/laiweichao/Documents/OpenOPC-main && opc ui
```

Expected: server starts at `http://localhost:8765` without errors.

- [ ] **Step 2: Seed an invite code**

In a second terminal:

```bash
opc user create-invite DEMOCODE1
```

Expected: output includes `Invite code created: DEMOCODE1`.

- [ ] **Step 3: Register through the browser**

Open `http://localhost:8765` in a browser. Expected: the `LoginScreen` renders (not the office app) — confirms `Root.tsx`'s pre-app gate works with no stored token.

Click "没有账号？注册", enter username `demo` and invite code `DEMOCODE1`, submit.

Expected: the login screen disappears and the normal office UI (workspace/office view) renders — confirms `/api/register` succeeded, `storeSession` ran, and the WS connection with `?token=...` was accepted by `handle_ws`.

- [ ] **Step 4: Confirm the session persists across reloads**

Reload the page.

Expected: the office UI renders directly, no login screen — confirms `getStoredToken()` in `Root.tsx` and the WS token query param both work after a fresh page load.

- [ ] **Step 5: Confirm a second registration with the same invite code is rejected**

Open a private/incognito browser window, navigate to `http://localhost:8765`, register with username `demo2` and invite code `DEMOCODE1`.

Expected: an error message appears on the form (e.g. "invite_code_used") and the login screen stays up — confirms the "each invite code registers exactly one account" rule from Task 1 is enforced end-to-end.

- [ ] **Step 6: Confirm login works with the already-registered account**

In the incognito window, clear the form (or open a fresh private window), switch to "已有账号？登录", enter username `demo` and invite code `DEMOCODE1`, submit.

Expected: the office UI renders — confirms `/api/login` + WS token auth succeed for an existing account from a separate browser/session.

- [ ] **Step 7: Confirm an invalid/cleared token is rejected**

In the browser devtools console (on the already-logged-in tab), run:

```js
localStorage.setItem('opc_session_token', 'not-a-real-token')
```

Reload the page.

Expected: the WS connection is closed by the server (close code 4401), `onAuthError` fires, `clearSession()` runs, and the page reloads back to the `LoginScreen` — confirms invalid tokens are rejected end-to-end rather than silently retried.
