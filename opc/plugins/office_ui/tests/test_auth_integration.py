"""Full-stack auth integration test: seeded invite code -> HTTP register/login ->
real WS connection authenticated through WSHandler.handle_ws / _authenticate_ws_request.

Unlike tests/test_ws_handler_auth.py (which calls _authenticate_ws_request directly
against a fake request object), this exercises the real aiohttp route end to end:
an actual WebSocket upgrade against handle_ws, with a real UserStore backing the
token lookup.
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
    """Minimal stand-in for OPCEngine.

    A real OPCEngine needs a store/opc_home to construct, which is unnecessary
    overhead for an auth test. WSHandler.handle_ws only needs an engine that
    behaves well enough for the initial snapshot/role-map/recovery-status steps
    it runs right after authenticating a connection.
    """
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


class AuthIntegrationTests(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self.user_db = await aiosqlite.connect(":memory:")
        self.agent_db = await aiosqlite.connect(":memory:")
        self.chat_db = await aiosqlite.connect(":memory:")

        self.user_store = UserStore(self.user_db)
        await self.user_store.initialize()
        await self.user_store.create_invite_code("INVITE1")

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

    async def test_register_then_websocket_connects_with_token(self) -> None:
        resp = await self.client.post(
            "/api/register", json={"username": "wsuser", "invite_code": "INVITE1"}
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["ok"])
        token = data["token"]

        async with self.client.ws_connect(f"/ws?token={token}") as ws:
            msg = await ws.receive(timeout=5)
            self.assertNotEqual(ws.close_code, 4401)
            self.assertEqual(msg.type, aiohttp.WSMsgType.TEXT)

    async def test_websocket_rejects_invalid_token(self) -> None:
        async with self.client.ws_connect("/ws?token=garbage") as ws:
            msg = await ws.receive(timeout=5)
            self.assertEqual(msg.type, aiohttp.WSMsgType.CLOSE)
            self.assertEqual(ws.close_code, 4401)


if __name__ == "__main__":
    unittest.main()
