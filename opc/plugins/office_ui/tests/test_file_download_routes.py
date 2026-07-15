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
