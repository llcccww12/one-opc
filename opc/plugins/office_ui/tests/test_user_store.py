from __future__ import annotations

import unittest

import aiosqlite

from opc.plugins.office_ui.user_store import UserStore


class UserStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = UserStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_register_with_valid_invite_code_succeeds(self) -> None:
        await self.store.create_invite_code("CODE1")
        user_id, error = await self.store.register("alice", "CODE1")
        self.assertIsNone(error)
        self.assertIsNotNone(user_id)

    async def test_create_invite_code_returns_true_when_newly_created(self) -> None:
        created = await self.store.create_invite_code("CODE1")
        self.assertTrue(created)

    async def test_create_invite_code_returns_false_when_already_exists(self) -> None:
        await self.store.create_invite_code("CODE1")
        created_again = await self.store.create_invite_code("CODE1")
        self.assertFalse(created_again)

    async def test_register_with_unknown_invite_code_fails(self) -> None:
        user_id, error = await self.store.register("alice", "BOGUS")
        self.assertIsNone(user_id)
        self.assertEqual(error, "invite_code_invalid")

    async def test_register_with_already_used_invite_code_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.register("alice", "CODE1")
        user_id, error = await self.store.register("bob", "CODE1")
        self.assertIsNone(user_id)
        self.assertEqual(error, "invite_code_used")

    async def test_register_with_duplicate_username_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.create_invite_code("CODE2")
        await self.store.register("alice", "CODE1")
        user_id, error = await self.store.register("alice", "CODE2")
        self.assertIsNone(user_id)
        self.assertEqual(error, "username_taken")

    async def test_authenticate_with_correct_credentials_succeeds(self) -> None:
        await self.store.create_invite_code("CODE1")
        registered_id, _ = await self.store.register("alice", "CODE1")
        user_id = await self.store.authenticate("alice", "CODE1")
        self.assertEqual(user_id, registered_id)

    async def test_authenticate_with_wrong_invite_code_fails(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.register("alice", "CODE1")
        user_id = await self.store.authenticate("alice", "WRONG")
        self.assertIsNone(user_id)

    async def test_authenticate_unknown_username_fails(self) -> None:
        user_id = await self.store.authenticate("nobody", "CODE1")
        self.assertIsNone(user_id)

    async def test_session_token_round_trip(self) -> None:
        await self.store.create_invite_code("CODE1")
        registered_id, _ = await self.store.register("alice", "CODE1")
        token = await self.store.create_session(registered_id)
        resolved_id = await self.store.get_user_id_for_token(token)
        self.assertEqual(resolved_id, registered_id)

    async def test_unknown_token_resolves_to_none(self) -> None:
        resolved_id = await self.store.get_user_id_for_token("bogus-token")
        self.assertIsNone(resolved_id)


class ProjectOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = await aiosqlite.connect(":memory:")
        self.store = UserStore(self.db)
        await self.store.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()

    async def test_get_project_owner_returns_none_when_unrecorded(self) -> None:
        owner = await self.store.get_project_owner("alpha")
        self.assertIsNone(owner)

    async def test_record_then_get_project_owner_round_trips(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        owner = await self.store.get_project_owner("alpha")
        self.assertEqual(owner, "user-1")

    async def test_record_project_owner_is_idempotent_first_writer_wins(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        await self.store.record_project_owner("alpha", "user-2")
        owner = await self.store.get_project_owner("alpha")
        self.assertEqual(owner, "user-1")

    async def test_list_project_owners_returns_all_rows(self) -> None:
        await self.store.record_project_owner("alpha", "user-1")
        await self.store.record_project_owner("beta", "user-2")
        owners = await self.store.list_project_owners()
        self.assertEqual(owners, {"alpha": "user-1", "beta": "user-2"})

    async def test_get_sole_user_id_returns_none_when_no_users(self) -> None:
        sole = await self.store.get_sole_user_id()
        self.assertIsNone(sole)

    async def test_get_sole_user_id_returns_the_only_user(self) -> None:
        await self.store.create_invite_code("CODE1")
        user_id, _ = await self.store.register("alice", "CODE1")
        sole = await self.store.get_sole_user_id()
        self.assertEqual(sole, user_id)

    async def test_get_sole_user_id_returns_none_when_multiple_users(self) -> None:
        await self.store.create_invite_code("CODE1")
        await self.store.create_invite_code("CODE2")
        await self.store.register("alice", "CODE1")
        await self.store.register("bob", "CODE2")
        sole = await self.store.get_sole_user_id()
        self.assertIsNone(sole)


if __name__ == "__main__":
    unittest.main()
