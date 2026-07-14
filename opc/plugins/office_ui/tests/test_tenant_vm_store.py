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

    async def test_reset_stale_launching_marks_launching_rows_as_error(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        count = await self.store.reset_stale_launching()
        self.assertEqual(count, 1)
        vm = await self.store.get_vm("user-1")
        self.assertEqual(vm["status"], "error")
        self.assertIsNotNone(vm["error_message"])

    async def test_reset_stale_launching_does_not_touch_ready_or_stopped_rows(self) -> None:
        await self.store.create_vm("user-1", "opc-tenant-abc123", "tok-abc")
        await self.store.update_status("user-1", "ready")
        await self.store.create_vm("user-2", "opc-tenant-def456", "tok-def")
        await self.store.update_status("user-2", "stopped")

        count = await self.store.reset_stale_launching()

        self.assertEqual(count, 0)
        vm1 = await self.store.get_vm("user-1")
        vm2 = await self.store.get_vm("user-2")
        self.assertEqual(vm1["status"], "ready")
        self.assertEqual(vm2["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
