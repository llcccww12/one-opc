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
