"""WS-level tests for get_vm_credentials / update_vm_credentials."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import aiosqlite

from opc.plugins.office_ui.credential_vault import CredentialVault
from opc.plugins.office_ui.ws_handler import WSHandler


class VmCredentialsWSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = await aiosqlite.connect(":memory:")
        self.vault = CredentialVault(self.db, self.tmp_dir / "credential_key")
        await self.vault.initialize()

    async def asyncTearDown(self) -> None:
        await self.db.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_handler(self, ws: Any, user_id: str | None) -> WSHandler:
        handler = object.__new__(WSHandler)
        handler._credential_vault = self.vault
        handler._client_user_ids = {ws: user_id} if user_id else {}
        handler._safe_send_json = AsyncMock()
        return handler

    async def test_get_vm_credentials_reports_unset_when_unconfigured(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertFalse(sent["payload"]["api_key_set"])

    async def test_get_vm_credentials_reports_set_after_update(self) -> None:
        await self.vault.set_credentials("user-1", "sk-key", "https://api.example.com")
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["api_key_set"])
        self.assertEqual(sent["payload"]["api_base"], "https://api.example.com")

    async def test_update_vm_credentials_stores_new_key(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "sk-new-key", "api_base": ""}})
        stored = await self.vault.get_credentials("user-1")
        self.assertEqual(stored[0], "sk-new-key")
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])

    async def test_update_vm_credentials_blank_key_keeps_existing(self) -> None:
        await self.vault.set_credentials("user-1", "sk-existing", "")
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(
            ws, {"patch": {"api_key": "", "api_base": "https://new-base.example.com"}}
        )
        stored = await self.vault.get_credentials("user-1")
        self.assertEqual(stored[0], "sk-existing")
        self.assertEqual(stored[1], "https://new-base.example.com")

    async def test_update_vm_credentials_without_key_ever_configured_errors(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, "user-1")
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "", "api_base": ""}})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "missing_api_key")

    async def test_anonymous_connection_get_reports_unset_not_error(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, None)
        await handler._handle_get_vm_credentials(ws, {})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertFalse(sent["payload"]["api_key_set"])

    async def test_anonymous_connection_update_is_rejected(self) -> None:
        ws = AsyncMock()
        handler = self._make_handler(ws, None)
        await handler._handle_update_vm_credentials(ws, {"patch": {"api_key": "sk-x", "api_base": ""}})
        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "unauthorized")


if __name__ == "__main__":
    unittest.main()
