from __future__ import annotations

import unittest

import aiosqlite

from opc.plugins.office_ui.tenant_vm_store import TenantVmStore


class TenantVmStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = TenantVmStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_get_vm_returns_none_when_unrecorded(self) -> None:
        vm = await self.store.get_vm("user-1")
        self.assertIsNone(vm)

    async def test_create_then_get_vm_round_trips(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        vm = await self.store.get_vm("user-1")
        self.assertIsNotNone(vm)
        self.assertEqual(vm["cluster_name"], "opc-tenant-abc123")
        self.assertEqual(vm["status"], "launching")
        self.assertEqual(vm["auth_token"], "tok-abc")
        self.assertIsNone(vm["error_message"])

    async def test_update_status_changes_status_and_error_message(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "error", "sky launch failed")
        vm = await self.store.get_vm("user-1")
        self.assertEqual(vm["status"], "error")
        self.assertEqual(vm["error_message"], "sky launch failed")

    async def test_update_status_to_ready_clears_previous_error(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "error", "boom")
        await self.store.update_status("user-1", "ready")
        vm = await self.store.get_vm("user-1")
        self.assertEqual(vm["status"], "ready")
        self.assertIsNone(vm["error_message"])


if __name__ == "__main__":
    unittest.main()
