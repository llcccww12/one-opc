"""Unit tests for ProjectService's per-user project ownership enforcement."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiosqlite

from opc.plugins.office_ui.services.context import ModeState, OfficeServiceContext
from opc.plugins.office_ui.services.models import ServiceError
from opc.plugins.office_ui.services.project import ProjectService
from opc.plugins.office_ui.user_store import UserStore


class ProjectServiceOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(".tmp-test-project-service")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "projects").mkdir(parents=True, exist_ok=True)

        self.db = await aiosqlite.connect(":memory:")
        self.user_store = UserStore(self.db)
        await self.user_store.initialize()

        fake_engine = SimpleNamespace(opc_home=self.tmp_dir, project_id="default")
        self.context = OfficeServiceContext(
            engine=fake_engine,
            agent_store=MagicMock(),
            chat_store=MagicMock(),
            event_adapter=MagicMock(),
            user_store=self.user_store,
            mode_state=ModeState(),
        )
        # Sandbox the workplace dir under tmp_dir; get_project_workplace() otherwise
        # resolves to the real shared workplace root beside the repo (see test_cli_app.py
        # for the same pattern), which would leak "alpha"/"legacy" dirs across test runs.
        workplace_root = self.tmp_dir / "workplace"
        self.context.project_workplace_hook = lambda project_id: workplace_root / project_id
        self.service = ProjectService(self.context)

    async def asyncTearDown(self) -> None:
        await self.db.close()
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def _register(self, username: str, code: str) -> str:
        await self.user_store.create_invite_code(code)
        user_id, _ = await self.user_store.register(username, code)
        assert user_id is not None
        return user_id

    async def test_project_created_by_user_a_not_in_user_bs_list(self) -> None:
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")

        await self.service.create("alpha", owner_user_id=user_a)

        result_b = await self.service.list(owner_user_id=user_b)
        ids_b = {p["id"] for p in result_b.payload["projects"]}
        self.assertNotIn("alpha", ids_b)

        result_a = await self.service.list(owner_user_id=user_a)
        ids_a = {p["id"] for p in result_a.payload["projects"]}
        self.assertIn("alpha", ids_a)

    async def test_user_b_calling_with_user_as_project_id_is_denied(self) -> None:
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")
        await self.service.create("alpha", owner_user_id=user_a)

        with self.assertRaises(ServiceError) as ctx:
            await self.service.assert_access("alpha", user_b)
        self.assertEqual(ctx.exception.code, "project_access_denied")

        await self.service.assert_access("alpha", user_a)  # owner is never denied

    async def test_anonymous_mode_is_unaffected(self) -> None:
        await self.service.create("alpha", owner_user_id=None)
        await self.service.assert_access("alpha", None)
        await self.service.assert_access("alpha", "anonymous")
        result = await self.service.list(owner_user_id=None)
        ids = {p["id"] for p in result.payload["projects"]}
        self.assertIn("alpha", ids)

    async def test_historical_project_is_migrated_to_sole_account(self) -> None:
        # Simulate a pre-existing project directory from before accounts existed.
        (self.tmp_dir / "projects" / "legacy").mkdir(parents=True, exist_ok=True)
        user_a = await self._register("alice", "CODE-A")

        result = await self.service.list(owner_user_id=user_a)
        ids = {p["id"] for p in result.payload["projects"]}
        self.assertIn("legacy", ids)
        self.assertEqual(await self.user_store.get_project_owner("legacy"), user_a)

    async def test_historical_project_stays_unassigned_with_multiple_accounts(self) -> None:
        (self.tmp_dir / "projects" / "legacy").mkdir(parents=True, exist_ok=True)
        user_a = await self._register("alice", "CODE-A")
        user_b = await self._register("bob", "CODE-B")

        result_a = await self.service.list(owner_user_id=user_a)
        result_b = await self.service.list(owner_user_id=user_b)
        self.assertNotIn("legacy", {p["id"] for p in result_a.payload["projects"]})
        self.assertNotIn("legacy", {p["id"] for p in result_b.payload["projects"]})
        self.assertIsNone(await self.user_store.get_project_owner("legacy"))


if __name__ == "__main__":
    unittest.main()
