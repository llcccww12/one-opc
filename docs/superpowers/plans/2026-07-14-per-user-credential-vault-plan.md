# 按用户 BYOK 模型凭证库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each logged-in user store their own encrypted Anthropic-compatible API key + base URL (BYOK), readable via a `CredentialVault.get_credentials(user_id)` method that sub-project 2's worker-dispatch code will call — and expose it through a new section in the existing identity-menu settings panel.

**Architecture:** A new `CredentialVault` (mirrors `UserStore`/`TenantVmStore`'s sqlite-in-`ui_state.db` pattern) encrypts the `api_key` column with Fernet before it touches disk, using an application-level key auto-generated at `.opc/credential_key` on first use. Two new WS request types (`get_vm_credentials`/`update_vm_credentials`) read/write it scoped to `self._client_user_ids[ws]` — the same per-connection user id sub-project "post-login-ux-and-tenant-isolation" already threads through `WSHandler`. The frontend adds a second, clearly-separated section to the existing `SettingsPanel` (which today only edits the global native-agent `LLMConfig`) labeled "模型 API Key" with help text pointing at where to get an Anthropic key.

**Tech Stack:** Python 3.10+, aiohttp/aiosqlite (existing), `cryptography` (new dependency — Fernet symmetric encryption). React 19 + TypeScript, zero test framework (`tsx` + `node:assert/strict`).

## Global Constraints

- Scope is **only** the worker/VM dispatch path's credential storage — the existing global `LLMConfig`/`SettingsService` (native Task Mode agent) is untouched. Do not add a `user_id` parameter anywhere in `opc/engine.py`, `opc/llm/provider.py`, or the native-agent call chain — that is a separate, much larger initiative (confirmed: ~100 call sites across 15 files) and explicitly out of scope here.
- `CredentialVault` is wired directly onto `WSHandler` as a new optional constructor parameter (mirrors `user_store`), **not** routed through `OfficeServiceContext`/`OfficeServices` — this is simple per-user key-value storage with no project/engine dependency, so the heavier services layer adds nothing.
- `api_key` is the only encrypted column; `api_base` is stored in plaintext (matches how the existing global `SettingsService.get_llm_config` already treats `api_base` as non-sensitive).
- The credential encryption key file (`.opc/credential_key`) is auto-generated on first use via `Fernet.generate_key()` — never require an operator to set an environment variable before this works. `os.chmod(path, 0o600)` is best-effort (wrapped in `try/except OSError`, since it is a no-op on Windows).
- "Leave the API Key field blank = keep the existing key" — matches the interaction convention already established by the global `SettingsPanel`'s model/API-key form.
- Backend tests run with `python -m pytest opc/plugins/office_ui/tests/<file>.py -q` (matches where `test_user_store.py`/`test_tenant_vm_store.py` already live). Frontend tests run with `npx tsx <file>.test.ts(x)` from `opc/plugins/office_ui/frontend_src`.
- Any new WS request type must be added to `docs/FRONTEND_BACKEND_MAP.md` in the same task that introduces it (matches the convention used for `get_llm_config`/`update_llm_config`/`list_nodes`).

---

### Task 1: `CredentialVault` — encrypted per-user credential storage

**Files:**
- Modify: `pyproject.toml` (add `cryptography` dependency)
- Create: `opc/plugins/office_ui/credential_vault.py`
- Test: `opc/plugins/office_ui/tests/test_credential_vault.py`

**Interfaces:**
- Produces: `class CredentialVault` with `__init__(self, db: aiosqlite.Connection, key_path: Path) -> None`, `async def initialize(self) -> None`, `async def get_credentials(self, user_id: str) -> tuple[str, str] | None` (returns `(api_key, api_base)` or `None` if unconfigured), `async def has_credentials(self, user_id: str) -> bool`, `async def set_credentials(self, user_id: str, api_key: str, api_base: str = "") -> None`.

- [ ] **Step 1: Add the `cryptography` dependency**

In `pyproject.toml`, insert `"cryptography>=42.0",` right after the existing `"pyyaml>=6.0",` line (line 20):

```toml
    "pyyaml>=6.0",
    "cryptography>=42.0",
    "aiosqlite>=0.19.0",
```

Run: `source .venv/bin/activate && python -c "import cryptography; print(cryptography.__version__)"`
Expected: prints a version (it's already present transitively in this repo's venv; this step makes it an explicit direct dependency so it isn't relying on another package's transitive pin).

- [ ] **Step 2: Write the failing tests**

Create `opc/plugins/office_ui/tests/test_credential_vault.py`:

```python
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

import aiosqlite

from opc.plugins.office_ui.credential_vault import CredentialVault


class CredentialVaultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = await aiosqlite.connect(":memory:")
        self.vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await self.vault.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def test_get_credentials_returns_none_when_unconfigured(self) -> None:
        result = await self.vault.get_credentials("user-1")
        self.assertIsNone(result)

    async def test_has_credentials_returns_false_when_unconfigured(self) -> None:
        self.assertFalse(await self.vault.has_credentials("user-1"))

    async def test_set_then_get_credentials_round_trips(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "https://api.example.com")
        result = await self.vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-secret-key", "https://api.example.com"))
        self.assertTrue(await self.vault.has_credentials("user-1"))

    async def test_api_key_is_encrypted_at_rest(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "")
        cursor = await self.db.execute(
            "SELECT api_key_encrypted FROM user_credentials WHERE user_id = ?", ("user-1",)
        )
        row = await cursor.fetchone()
        self.assertNotIn("sk-secret-key", row[0])

    async def test_two_users_have_independent_credentials(self) -> None:
        await self.vault.set_credentials("user-1", "sk-key-one", "")
        await self.vault.set_credentials("user-2", "sk-key-two", "")
        result_1 = await self.vault.get_credentials("user-1")
        result_2 = await self.vault.get_credentials("user-2")
        self.assertEqual(result_1[0], "sk-key-one")
        self.assertEqual(result_2[0], "sk-key-two")

    async def test_set_credentials_overwrites_previous_value(self) -> None:
        await self.vault.set_credentials("user-1", "sk-old-key", "https://old.example.com")
        await self.vault.set_credentials("user-1", "sk-new-key", "https://new.example.com")
        result = await self.vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-new-key", "https://new.example.com"))

    async def test_key_file_is_reused_across_instances(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "")
        second_vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await second_vault.initialize()
        result = await second_vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-secret-key", ""))

    @unittest.skipIf(os.name == "nt", "chmod is a no-op on Windows")
    async def test_key_file_has_restrictive_permissions(self) -> None:
        key_path = self.tmp_dir / "credential_key"
        mode = stat.S_IMODE(key_path.stat().st_mode)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_credential_vault.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opc.plugins.office_ui.credential_vault'`

- [ ] **Step 4: Write the implementation**

Create `opc/plugins/office_ui/credential_vault.py`:

```python
"""Per-user encrypted BYOK model-credential storage.

Scoped to the worker/VM dispatch path only (the external claude_code agent
running on a user's own SkyPilot VM) — the native-agent LLM path stays on
the existing global LLMConfig/SettingsService and is out of scope here;
threading user_id through it touches ~100 call sites across 15 files and
is a separate initiative.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet


def _load_or_create_key(key_path: Path) -> bytes:
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # best-effort; e.g. a no-op on Windows
    return key


class CredentialVault:
    """Persists one BYOK (api_key, api_base) pair per user in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection, key_path: Path) -> None:
        self._db = db
        self._fernet = Fernet(_load_or_create_key(key_path))
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                api_key_encrypted TEXT NOT NULL,
                api_base TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def get_credentials(self, user_id: str) -> tuple[str, str] | None:
        cursor = await self._db.execute(
            "SELECT api_key_encrypted, api_base FROM user_credentials WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        api_key = self._fernet.decrypt(row[0].encode("utf-8")).decode("utf-8")
        return api_key, row[1] or ""

    async def has_credentials(self, user_id: str) -> bool:
        return await self.get_credentials(user_id) is not None

    async def set_credentials(self, user_id: str, api_key: str, api_base: str = "") -> None:
        encrypted = self._fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")
        async with self._write_lock:
            now = time.time()
            await self._db.execute(
                "INSERT INTO user_credentials (user_id, api_key_encrypted, api_base, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "api_key_encrypted = excluded.api_key_encrypted, "
                "api_base = excluded.api_base, "
                "updated_at = excluded.updated_at",
                (user_id, encrypted, api_base, now),
            )
            await self._db.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_credential_vault.py -v`
Expected: PASS (8 tests, or 7 if running on Windows where the permissions test is skipped)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml opc/plugins/office_ui/credential_vault.py opc/plugins/office_ui/tests/test_credential_vault.py
git commit -m "feat: add CredentialVault for per-user encrypted BYOK model credentials"
```

---

### Task 2: WS handlers `get_vm_credentials` / `update_vm_credentials`

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py`
- Modify: `opc/plugins/office_ui/server.py`
- Modify: `docs/FRONTEND_BACKEND_MAP.md`
- Test: `opc/plugins/office_ui/tests/test_credential_vault_ws.py`

**Interfaces:**
- Consumes: `CredentialVault.get_credentials`/`set_credentials` (Task 1).
- Produces: `WSHandler.__init__(..., user_store=None, credential_vault: CredentialVault | None = None)` (new 6th optional parameter); WS request types `get_vm_credentials` (no payload) and `update_vm_credentials` (`{"type": "update_vm_credentials", "patch": {"api_key": "...", "api_base": "..."}}`), both replying via a message of the same `type` with `payload.ok`.

- [ ] **Step 1: Write the failing tests**

Create `opc/plugins/office_ui/tests/test_credential_vault_ws.py`:

```python
"""WS-level tests for get_vm_credentials / update_vm_credentials."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import aiosqlite

from opc.plugins.office_ui.credential_vault import CredentialVault
from opc.plugins.office_ui.ws_handler import WSHandler


class VmCredentialsWSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = await aiosqlite.connect(":memory:")
        self.vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await self.vault.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_handler(self, ws: Any, user_id: str | None) -> WSHandler:
        handler = object.__new__(WSHandler)
        handler._credential_vault = self.vault
        handler._client_user_ids = {ws: user_id} if user_id else {}
        handler._safe_send_json = AsyncMock()
        return handler

    async def test_get_vm_credentials_reports_unset_when_unconfigured(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertFalse(sent["payload"]["api_key_set"])

    async def test_get_vm_credentials_reports_set_after_update(self) -> None:
        await self.vault.set_credentials("user-1", "sk-key", "https://api.example.com")
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["api_key_set"])
        self.assertEqual(sent["payload"]["api_base"], "https://api.example.com")

    async def test_update_vm_credentials_stores_new_key(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "sk-new-key", "api_base": ""}})
        stored = await self.vault.get_credentials("user-1")
        self.assertEqual(stored[0], "sk-new-key")
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])

    async def test_update_vm_credentials_blank_key_keeps_existing(self) -> None:
        await self.vault.set_credentials("user-1", "sk-existing", "")
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(
            ws, {"patch": {"api_key": "", "api_base": "https://new-base.example.com"}}
        )
        stored = await self.vault.get_credentials("user-1")
        self.assertEqual(stored[0], "sk-existing")
        self.assertEqual(stored[1], "https://new-base.example.com")

    async def test_update_vm_credentials_without_key_ever_configured_errors(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "", "api_base": ""}})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "missing_api_key")

    async def test_anonymous_connection_get_reports_unset_not_error(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, None)
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertFalse(sent["payload"]["api_key_set"])

    async def test_anonymous_connection_update_is_rejected(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, None)
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "sk-x", "api_base": ""}})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest opc/plugins/office_ui/tests/test_credential_vault_ws.py -v`
Expected: FAIL with `AttributeError: 'WSHandler' object has no attribute '_handle_get_vm_credentials'`

- [ ] **Step 3: Implement — `ws_handler.py`**

Add `CredentialVault` to the existing `TYPE_CHECKING` import block (alongside `UserStore`):

```python
    from opc.plugins.office_ui.credential_vault import CredentialVault
```

Change the `WSHandler.__init__` signature (currently at line 436-443):

```python
    def __init__(
        self,
        engine: OPCEngine,
        agent_store: AgentStore,
        chat_store: ChatStore,
        event_adapter: EventAdapter,
        user_store: UserStore | None = None,
        credential_vault: CredentialVault | None = None,
    ) -> None:
```

Right after the existing `self._user_store = user_store` line (line 451), add:

```python
        self._credential_vault = credential_vault
```

Add the two handlers near `_handle_get_llm_config`/`_handle_update_llm_config` (right after `_handle_update_llm_config`, before `_handle_list_nodes`):

```python
    async def _handle_get_vm_credentials(self, ws: Any, data: dict) -> None:
        user_id = self._client_user_ids.get(ws)
        api_key_set = False
        api_base = ""
        if user_id and user_id != "anonymous" and self._credential_vault is not None:
            creds = await self._credential_vault.get_credentials(user_id)
            if creds is not None:
                api_key_set = True
                api_base = creds[1]
        await self._safe_send_json(
            ws, {"type": "get_vm_credentials", "payload": {"ok": True, "api_key_set": api_key_set, "api_base": api_base}}
        )

    async def _handle_update_vm_credentials(self, ws: Any, data: dict) -> None:
        user_id = self._client_user_ids.get(ws)
        if not user_id or user_id == "anonymous" or self._credential_vault is None:
            await self._safe_send_json(
                ws, {"type": "update_vm_credentials", "payload": {"ok": False, "error": "unauthorized"}}
            )
            return

        patch = data.get("patch", {}) or {}
        api_base = str(patch.get("api_base") or "")
        new_key = str(patch.get("api_key") or "").strip()

        key_to_store = new_key
        if not key_to_store:
            existing = await self._credential_vault.get_credentials(user_id)
            key_to_store = existing[0] if existing else ""

        if not key_to_store:
            await self._safe_send_json(
                ws, {"type": "update_vm_credentials", "payload": {"ok": False, "error": "missing_api_key"}}
            )
            return

        await self._credential_vault.set_credentials(user_id, key_to_store, api_base)
        await self._safe_send_json(
            ws, {"type": "update_vm_credentials", "payload": {"ok": True, "api_key_set": True, "api_base": api_base}}
        )
```

Register both in the `_HANDLERS` dict, right after the existing `"update_llm_config": _handle_update_llm_config,` entry:

```python
        "get_vm_credentials":    _handle_get_vm_credentials,
        "update_vm_credentials": _handle_update_vm_credentials,
```

- [ ] **Step 4: Implement — wire into `server.py`**

Add an import right after the existing `from opc.plugins.office_ui.user_store import UserStore` line:

```python
from opc.plugins.office_ui.credential_vault import CredentialVault
```

Right after the existing block:

```python
    user_store = UserStore(db)
    await user_store.initialize()
```

insert:

```python

    credential_vault = CredentialVault(db, opc_home / "credential_key")
    await credential_vault.initialize()
```

Change the `WSHandler` construction line from:

```python
    ws_handler = WSHandler(engine, agent_store, chat_store, event_adapter, user_store)
```

to:

```python
    ws_handler = WSHandler(engine, agent_store, chat_store, event_adapter, user_store, credential_vault)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest opc/plugins/office_ui/tests/test_credential_vault_ws.py -v`
Expected: PASS (7 tests)

Then run the broader WS handler regression suite to confirm the new constructor param didn't break existing call sites:

Run: `python -m pytest opc/plugins/office_ui/tests/ tests/test_ws_handler_escalations.py tests/test_ws_handler_auth.py -q`
Expected: all PASS

- [ ] **Step 6: Document in FRONTEND_BACKEND_MAP.md**

In `docs/FRONTEND_BACKEND_MAP.md`, add a new section right after the "全局模型 / API Key 设置" section (added by an earlier plan):

```markdown
## 二十、按用户 BYOK 模型凭证（VM/worker 派发用）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | WS 响应类型 |
|------|----------|-------------|--------------|-------------|
| 读取当前用户凭证 | SettingsPanel | `get_vm_credentials` | `_handle_get_vm_credentials` | 同类型消息 |
| 保存当前用户凭证 | SettingsPanel | `update_vm_credentials` | `_handle_update_vm_credentials` | 同类型消息 |
```

- [ ] **Step 7: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py opc/plugins/office_ui/server.py docs/FRONTEND_BACKEND_MAP.md opc/plugins/office_ui/tests/test_credential_vault_ws.py
git commit -m "feat: wire get_vm_credentials/update_vm_credentials WS request types"
```

---

### Task 3: Frontend `wsClient` — `getVmCredentials` / `updateVmCredentials`

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`
- Test: `opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts` (existing file — append assertions)

**Interfaces:**
- Produces: `VisualSocketClient.getVmCredentials(): void`, `VisualSocketClient.updateVmCredentials(patch: { api_key?: string; api_base?: string }): void`, and two new `SocketHandlers` callbacks `onGetVmCredentials?: (payload: { ok: boolean; api_key_set: boolean; api_base: string }) => void` and `onUpdateVmCredentials?: (payload: { ok: boolean; api_key_set?: boolean; api_base?: string; error?: string }) => void`.

- [ ] **Step 1: Write the failing assertions**

Append to `opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts` (before the final `console.log`/closing of the file — read the existing file first to match its exact structure, then add these new `assert.match` calls alongside the existing `get_llm_config`/`update_llm_config` ones):

```ts
assert.match(source, /getVmCredentials\(\): void \{\s*this\.send\(\{ type: 'get_vm_credentials' \}\)/, 'getVmCredentials must send a get_vm_credentials message')
assert.match(source, /updateVmCredentials\(patch:/, 'updateVmCredentials must accept a patch object')
assert.match(source, /type: 'update_vm_credentials', patch/, 'updateVmCredentials must send patch in the payload')
assert.match(source, /onGetVmCredentials\?:/, 'SocketHandlers must declare onGetVmCredentials')
assert.match(source, /onUpdateVmCredentials\?:/, 'SocketHandlers must declare onUpdateVmCredentials')
assert.match(source, /case 'get_vm_credentials':\s*this\.handlers\.onGetVmCredentials\?\.\(parsed\.payload/, 'handleMessage must dispatch get_vm_credentials to onGetVmCredentials')
assert.match(source, /case 'update_vm_credentials':\s*this\.handlers\.onUpdateVmCredentials\?\.\(parsed\.payload/, 'handleMessage must dispatch update_vm_credentials to onUpdateVmCredentials')
```

(Note: this file tests source text of `wsClient.ts` itself, not a separate compiled module — check the existing file's exact `const source = ...` variable name before appending, and add these lines using that same variable.)

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
Expected: FAIL — `AssertionError` on the first `getVmCredentials` regex (method doesn't exist yet)

- [ ] **Step 3: Implement**

In `opc/plugins/office_ui/frontend_src/lib/wsClient.ts`, add the two handler declarations to the `SocketHandlers` interface, right after the existing `onUpdateLlmConfig?: ...` line:

```ts
  onGetVmCredentials?: (payload: { ok: boolean; api_key_set: boolean; api_base: string }) => void
  onUpdateVmCredentials?: (payload: { ok: boolean; api_key_set?: boolean; api_base?: string; error?: string }) => void
```

Add the two send methods to `VisualSocketClient`, right after the existing `updateLlmConfig` method (line 642-644):

```ts
  getVmCredentials(): void {
    this.send({ type: 'get_vm_credentials' })
  }

  updateVmCredentials(patch: { api_key?: string; api_base?: string }): void {
    this.send({ type: 'update_vm_credentials', patch })
  }
```

Add the two dispatch cases inside `handleMessage`'s `switch`, right after the existing `update_llm_config` case (line 852-854):

```ts
      case 'get_vm_credentials':
        this.handlers.onGetVmCredentials?.(parsed.payload as { ok: boolean; api_key_set: boolean; api_base: string })
        break
      case 'update_vm_credentials':
        this.handlers.onUpdateVmCredentials?.(parsed.payload as { ok: boolean; api_key_set?: boolean; api_base?: string; error?: string })
        break
```

`get_vm_credentials`/`update_vm_credentials` are not project-scoped — do not add them to `PROJECT_SCOPED_MESSAGE_TYPES`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
Expected: PASS, prints the existing pass message plus no new failures

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/lib/wsClient.ts opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts
git commit -m "feat: add getVmCredentials/updateVmCredentials to wsClient"
```

---

### Task 4: `SettingsPanel` — add the "模型 API Key" (VM credential) section

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`

**Interfaces:**
- Consumes: nothing directly from `wsClient` (stays presentational, per the existing convention this component's own test already enforces).
- Produces: `SettingsPanel` gains four new props: `vmCredentials: { api_key_set: boolean; api_base: string } | null`, `onRequestVmCredentials: () => void`, `onSaveVmCredentials: (patch: { api_key?: string; api_base?: string }) => void`, `vmCredentialsSaveMessage: string`.

- [ ] **Step 1: Write the failing assertions**

Append to `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx` (before the final `console.log`):

```ts
assert.match(source, /onRequestVmCredentials\(\)/, 'SettingsPanel must request current VM credentials on open')
assert.match(source, /onSaveVmCredentials\(/, 'SettingsPanel must call onSaveVmCredentials on save')
assert.match(source, /console\.anthropic\.com/, 'SettingsPanel must link to where to obtain an Anthropic API key')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
Expected: FAIL on the `onRequestVmCredentials` assertion

- [ ] **Step 3: Implement**

Replace the full contents of `opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

export interface LlmConfigPayload {
  default_model: string
  api_base: string
  api_key_set: boolean
}

export interface VmCredentialsPayload {
  api_key_set: boolean
  api_base: string
}

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
  vmCredentials: VmCredentialsPayload | null
  onRequestVmCredentials: () => void
  onSaveVmCredentials: (patch: { api_key?: string; api_base?: string }) => void
  vmCredentialsSaveMessage: string
}

export function SettingsPanel({
  open,
  onClose,
  llmConfig,
  onRequestLlmConfig,
  onSaveLlmConfig,
  saveMessage,
  vmCredentials,
  onRequestVmCredentials,
  onSaveVmCredentials,
  vmCredentialsSaveMessage,
}: SettingsPanelProps) {
  const [defaultModel, setDefaultModel] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [vmApiBase, setVmApiBase] = useState('')
  const [vmApiKey, setVmApiKey] = useState('')

  useEffect(() => {
    if (!open) return
    onRequestLlmConfig()
    onRequestVmCredentials()
  }, [open, onRequestLlmConfig, onRequestVmCredentials])

  useEffect(() => {
    if (!llmConfig) return
    setDefaultModel(llmConfig.default_model)
    setApiBase(llmConfig.api_base)
  }, [llmConfig])

  useEffect(() => {
    if (!vmCredentials) return
    setVmApiBase(vmCredentials.api_base)
  }, [vmCredentials])

  useEffect(() => {
    if (saveMessage === 'Saved') setApiKey('')
  }, [saveMessage])

  useEffect(() => {
    if (vmCredentialsSaveMessage === 'Saved') setVmApiKey('')
  }, [vmCredentialsSaveMessage])

  if (!open) return null

  const handleSave = () => {
    onSaveLlmConfig({
      default_model: defaultModel,
      api_base: apiBase,
      ...(apiKey ? { api_key: apiKey } : {}),
    })
  }

  const handleSaveVmCredentials = () => {
    onSaveVmCredentials({
      api_base: vmApiBase,
      ...(vmApiKey ? { api_key: vmApiKey } : {}),
    })
  }

  return createPortal(
    <div className="settings-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-panel-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">Settings</span>
            <h3 id="settings-panel-title" className="org-create-title">Model / API Key</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
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
          <button type="button" className="settings-save-btn" onClick={handleSave}>Save</button>
        </div>
        <div className="org-create-panel">
          <div className="org-create-eyebrow">模型 API Key（用于你的专属云主机）</div>
          <p>
            这个 Key 会被转发给你专属云主机里运行的 Claude Code 使用，不会被其他用户看到或使用。
            可以在 <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">Anthropic 官网</a> 申请，
            或使用第三方中转服务提供的 key + Base URL。
          </p>
          <label className="org-create-field">
            <span>API Key {vmCredentials?.api_key_set && !vmApiKey ? '(already set)' : ''}</span>
            <input
              type="password"
              value={vmApiKey}
              onChange={e => setVmApiKey(e.target.value)}
              placeholder={vmCredentials?.api_key_set ? 'Leave blank to keep current key' : ''}
            />
          </label>
          <label className="org-create-field">
            <span>Base URL</span>
            <input value={vmApiBase} onChange={e => setVmApiBase(e.target.value)} placeholder="(default)" />
          </label>
          {vmCredentialsSaveMessage && <div className="org-create-eyebrow">{vmCredentialsSaveMessage}</div>}
          <button type="button" className="settings-save-btn" onClick={handleSaveVmCredentials}>Save</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
Expected: PASS, prints `SettingsPanel.test.tsx passed`

Then run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors attributable to `SettingsPanel.tsx` (this task will produce a type error in `IdentityMenu.tsx` — its `<SettingsPanel>` call site is missing the 4 new required props — that is expected here and gets fixed in Task 5; only check that `SettingsPanel.tsx` itself has no new errors).

- [ ] **Step 5: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/SettingsPanel.tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx
git commit -m "feat: add per-user VM model API key section to SettingsPanel"
```

---

### Task 5: `IdentityMenu` + `App.tsx` wiring

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/auth/IdentityMenu.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx`

**Interfaces:**
- Consumes: `SettingsPanel`'s new props (Task 4), `VisualSocketClient.getVmCredentials`/`updateVmCredentials` (Task 3).
- Produces: `IdentityMenu` forwards the 4 new props straight through to `SettingsPanel` (same "App.tsx owns all wsClient state" convention already used for `llmConfig`).

- [ ] **Step 1: Implement — `IdentityMenu.tsx`**

Change the `IdentityMenuProps` interface (currently lines 7-12) to:

```tsx
interface IdentityMenuProps {
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
  vmCredentials: VmCredentialsPayload | null
  onRequestVmCredentials: () => void
  onSaveVmCredentials: (patch: { api_key?: string; api_base?: string }) => void
  vmCredentialsSaveMessage: string
}
```

Change the import line (line 4) to also bring in `VmCredentialsPayload`:

```tsx
import { SettingsPanel, type LlmConfigPayload, type VmCredentialsPayload } from './SettingsPanel'
```

Change the function signature (line 14) to destructure the new props:

```tsx
export function IdentityMenu({
  llmConfig,
  onRequestLlmConfig,
  onSaveLlmConfig,
  saveMessage,
  vmCredentials,
  onRequestVmCredentials,
  onSaveVmCredentials,
  vmCredentialsSaveMessage,
}: IdentityMenuProps) {
```

Change the `<SettingsPanel ... />` call site (currently lines 73-80) to forward the new props:

```tsx
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        llmConfig={llmConfig}
        onRequestLlmConfig={onRequestLlmConfig}
        onSaveLlmConfig={onSaveLlmConfig}
        saveMessage={saveMessage}
        vmCredentials={vmCredentials}
        onRequestVmCredentials={onRequestVmCredentials}
        onSaveVmCredentials={onSaveVmCredentials}
        vmCredentialsSaveMessage={vmCredentialsSaveMessage}
      />
```

- [ ] **Step 2: Implement — `App.tsx`**

Add state right after the existing `const [llmConfigSaveMessage, setLlmConfigSaveMessage] = useState('')` line (line 518):

```tsx
  const [vmCredentials, setVmCredentials] = useState<{ api_key_set: boolean; api_base: string } | null>(null)
  const [vmCredentialsSaveMessage, setVmCredentialsSaveMessage] = useState('')
```

Add request/save callbacks right after the existing `saveLlmConfig` callback (line 521):

```tsx
  const requestVmCredentials = useCallback(() => { clientRef.current?.getVmCredentials() }, [])
  const saveVmCredentials = useCallback((patch: { api_key?: string; api_base?: string }) => { clientRef.current?.updateVmCredentials(patch) }, [])
```

Add two handlers to the `VisualSocketClient` construction's handlers object literal, right after the existing `onUpdateLlmConfig` handler (lines 1657-1667... find the closing of that block and insert after it):

```tsx
      onGetVmCredentials: (payload) => {
        setVmCredentials({ api_key_set: payload.api_key_set, api_base: payload.api_base })
      },
      onUpdateVmCredentials: (payload) => {
        if (payload.ok) {
          setVmCredentials({
            api_key_set: Boolean(payload.api_key_set),
            api_base: payload.api_base ?? '',
          })
          setVmCredentialsSaveMessage('Saved')
        } else {
          setVmCredentialsSaveMessage(payload.error || 'Save failed')
        }
      },
```

Change the `<IdentityMenu ... />` call site (currently lines 2297-2302) to forward the new props:

```tsx
          <IdentityMenu
            llmConfig={llmConfig}
            onRequestLlmConfig={requestLlmConfig}
            onSaveLlmConfig={saveLlmConfig}
            saveMessage={llmConfigSaveMessage}
            vmCredentials={vmCredentials}
            onRequestVmCredentials={requestVmCredentials}
            onSaveVmCredentials={saveVmCredentials}
            vmCredentialsSaveMessage={vmCredentialsSaveMessage}
          />
```

- [ ] **Step 3: Run typecheck and existing regression tests**

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in `IdentityMenu.tsx`/`App.tsx`/`SettingsPanel.tsx` (the missing-props error from Task 4 is now fixed).

Run: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
Expected: PASS (existing assertions still hold — this task only adds props, doesn't remove anything the test checks for).

- [ ] **Step 4: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/auth/IdentityMenu.tsx opc/plugins/office_ui/frontend_src/App.tsx
git commit -m "feat: wire per-user VM credential state through IdentityMenu/App"
```

---

### Task 6: Full-stack verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend and frontend test suites**

Run: `python -m pytest opc/plugins/office_ui/tests/ -q`
Expected: PASS, zero regressions from Tasks 1-2.

Run: `cd opc/plugins/office_ui/frontend_src && npx tsx --test lib/wsClient.test.ts auth/SettingsPanel.test.tsx auth/IdentityMenu.test.tsx App.test.tsx`
Expected: PASS.

Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
Expected: no new errors in files touched by this plan.

- [ ] **Step 2: Rebuild and manually verify in a real browser**

```bash
cd opc/plugins/office_ui/frontend_src && npm run build
cd /Users/laiweichao/Documents/OpenOPC-main && opc ui
```

Register two accounts (A and B) via the login screen (reuse `opc user create-invite` to seed invite codes, as in the account-system plan).

As A: open the identity menu → settings panel → scroll to "模型 API Key（用于你的专属云主机）" → enter a fake key `sk-test-a` and save. Confirm the toast shows "Saved" and the field now shows "(already set)" placeholder text on next open.

Log out, log in as B. Open the same panel — confirm it shows **no** "(already set)" (B has not configured anything yet, confirming A's key is not visible to B).

As B: enter a different fake key `sk-test-b` and save.

In a Python shell (with `.venv` activated), directly query `ui_state.db`'s `user_credentials` table and confirm there are two rows with different `api_key_encrypted` values, and that `CredentialVault(db, opc_home / "credential_key").get_credentials(<A's user_id>)` returns `("sk-test-a", "")` while the same call for B's `user_id` returns `("sk-test-b", "")` — confirming per-user isolation end-to-end, not just at the UI layer.
