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
