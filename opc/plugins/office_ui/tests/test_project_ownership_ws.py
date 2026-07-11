"""Full-stack test: two accounts, cross-project WS access must be rejected.

Mirrors test_auth_integration.py's harness (real UserStore/aiosqlite, real
handle_ws route) but adds a second registered account and asserts that
sending a project-scoped message with the other account's project_id is
rejected with `project_access_denied`.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
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


def _make_stub_engine(opc_home: Path) -> MagicMock:
    engine = MagicMock()
    engine.project_id = "default"
    engine.opc_home = opc_home
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
        # create_project/list_projects touch the real filesystem (project dir,
        # memory file, workplace dir) via the default OfficeServiceContext hooks.
        # Isolate them under a tmp root so this test neither depends on nor
        # pollutes the repo's real .opc/projects or sibling *_workplace dirs.
        self._tmp_root = Path(tempfile.mkdtemp(prefix="opc-ownership-ws-test-"))
        opc_home = self._tmp_root / ".opc"
        workplace_root = self._tmp_root / "workplace"
        opc_home.mkdir(parents=True, exist_ok=True)
        workplace_root.mkdir(parents=True, exist_ok=True)

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
        self.engine = _make_stub_engine(opc_home)
        self.ws_handler = WSHandler(
            self.engine, self.agent_store, self.chat_store, self.event_adapter, self.user_store
        )
        self.ws_handler.services_context.project_workplace_hook = (
            lambda project_id: workplace_root / project_id
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
        shutil.rmtree(self._tmp_root, ignore_errors=True)
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
