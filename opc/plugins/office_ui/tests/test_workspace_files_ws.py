"""WS-level tests for list_workspace_files / delete_workspace_file."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler(worker_registry, user_store) -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.engine.worker_registry = worker_registry
    handler._user_store = user_store
    handler._safe_send_json = AsyncMock()
    return handler


class WorkspaceFilesWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_workspace_files_reports_error_when_no_owner(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = None
        handler = _make_handler(MagicMock(), user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "worker_not_connected")

    async def test_list_workspace_files_reports_error_when_worker_not_connected(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = False
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "worker_not_connected")

    async def test_list_workspace_files_returns_entries_on_success(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "dir_listing", "entries": [{"name": "a.txt"}]})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["entries"], [{"name": "a.txt"}])

    async def test_list_workspace_files_returns_error_when_dispatch_times_out(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value=None)
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_list_workspace_files(ws, {"project_id": "demo", "path": ""})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "timeout")

    async def test_delete_workspace_file_returns_ok_on_success(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "delete_result", "ok": True})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_delete_workspace_file(ws, {"project_id": "demo", "path": "notes.txt"})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertTrue(sent["payload"]["ok"])

    async def test_delete_workspace_file_forwards_worker_error(self) -> None:
        user_store = AsyncMock()
        user_store.get_project_owner.return_value = "user-1"
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_request = AsyncMock(return_value={"type": "delete_result", "ok": False, "error": "not_found"})
        handler = _make_handler(registry, user_store)
        ws = AsyncMock()

        await handler._handle_delete_workspace_file(ws, {"project_id": "demo", "path": "notes.txt"})

        sent = handler._safe_send_json.await_args.args[1]
        self.assertFalse(sent["payload"]["ok"])
        self.assertEqual(sent["payload"]["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
