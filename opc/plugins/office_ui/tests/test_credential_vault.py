from __future__ import annotations

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

import aiosqlite

from opc.plugins.office_ui.credential_vault import CredentialVault


class CredentialVaultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = await aiosqlite.connect(":memory:")
        self.vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await self.vault.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    async def test_get_credentials_returns_none_when_unconfigured(self) -> None:
        result = await self.vault.get_credentials("user-1")
        self.assertIsNone(result)

    async def test_has_credentials_returns_false_when_unconfigured(self) -> None:
        self.assertFalse(await self.vault.has_credentials("user-1"))

    async def test_set_then_get_credentials_round_trips(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "https://api.example.com")
        result = await self.vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-secret-key", "https://api.example.com"))
        self.assertTrue(await self.vault.has_credentials("user-1"))

    async def test_api_key_is_encrypted_at_rest(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "")
        cursor = await self.db.execute(
            "SELECT api_key_encrypted FROM user_credentials WHERE user_id = ?", ("user-1",)
        )
        row = await cursor.fetchone()
        self.assertNotIn("sk-secret-key", row[0])

    async def test_two_users_have_independent_credentials(self) -> None:
        await self.vault.set_credentials("user-1", "sk-key-one", "")
        await self.vault.set_credentials("user-2", "sk-key-two", "")
        result_1 = await self.vault.get_credentials("user-1")
        result_2 = await self.vault.get_credentials("user-2")
        self.assertEqual(result_1[0], "sk-key-one")
        self.assertEqual(result_2[0], "sk-key-two")

    async def test_set_credentials_overwrites_previous_value(self) -> None:
        await self.vault.set_credentials("user-1", "sk-old-key", "https://old.example.com")
        await self.vault.set_credentials("user-1", "sk-new-key", "https://new.example.com")
        result = await self.vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-new-key", "https://new.example.com"))

    async def test_key_file_is_reused_across_instances(self) -> None:
        await self.vault.set_credentials("user-1", "sk-secret-key", "")
        second_vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await second_vault.initialize()
        result = await second_vault.get_credentials("user-1")
        self.assertEqual(result, ("sk-secret-key", ""))

    @unittest.skipIf(os.name == "nt", "chmod is a no-op on Windows")
    async def test_key_file_has_restrictive_permissions(self) -> None:
        key_path = self.tmp_dir / "credential_key"
        mode = stat.S_IMODE(key_path.stat().st_mode)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
