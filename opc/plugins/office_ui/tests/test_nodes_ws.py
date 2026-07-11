"""WS-level test for list_nodes."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler() -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.agent_store = MagicMock()
    handler.chat_store = MagicMock()
    handler.event_adapter = MagicMock()
    handler._user_store = None
    handler._exec_mode = "task"
    handler._company_profile = "corporate"
    handler._task_preferred_agent = "native"
    return handler


class NodesWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_nodes_acks_unavailable_when_sky_missing(self) -> None:
        handler = _make_handler()
        ws = AsyncMock()
        with patch("shutil.which", return_value=None):
            await handler._handle_list_nodes(ws, {})
        sent = ws.send_json.await_args.args[0]
        # Sent directly via _safe_send_json with its own type (not the generic "ack"),
        # so the frontend's `case 'list_nodes':` dispatch in wsClient.ts can fire.
        self.assertEqual(sent["type"], "list_nodes")
        self.assertFalse(sent["payload"]["available"])


if __name__ == "__main__":
    unittest.main()
