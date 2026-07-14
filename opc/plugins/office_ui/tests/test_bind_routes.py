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
