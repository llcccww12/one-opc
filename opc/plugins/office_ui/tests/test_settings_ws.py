"""WS-level tests for get_llm_config / update_llm_config."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from opc.core.config import OPCConfig
from opc.plugins.office_ui.ws_handler import WSHandler


def _make_handler() -> WSHandler:
    handler = object.__new__(WSHandler)
    handler.engine = MagicMock()
    handler.engine.config = OPCConfig()
    handler.agent_store = MagicMock()
    handler.chat_store = MagicMock()
    handler.event_adapter = MagicMock()
    handler._user_store = None
    handler._exec_mode = "task"
    handler._company_profile = "corporate"
    handler._task_preferred_agent = "native"
    return handler


class SettingsWSTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_llm_config_acks_current_values(self) -> None:
        handler = _make_handler()
        handler.engine.config.llm.default_model = "anthropic/claude-sonnet-4-20250514"
        ws = AsyncMock()
        await handler._handle_get_llm_config(ws, {})
        sent = ws.send_json.await_args.args[0] if ws.send_json.await_args else None
        # _send_ack routes through _safe_send_json -> ws.send_json in this fake.
        self.assertIsNotNone(sent)
        self.assertEqual(sent["payload"]["default_model"], "anthropic/claude-sonnet-4-20250514")

    async def test_update_llm_config_applies_patch(self) -> None:
        handler = _make_handler()
        from unittest.mock import patch as mock_patch
        ws = AsyncMock()
        with mock_patch.object(OPCConfig, "save"):
            await handler._handle_update_llm_config(ws, {"patch": {"default_model": "anthropic/claude-opus-4-1"}})
        self.assertEqual(handler.engine.config.llm.default_model, "anthropic/claude-opus-4-1")


if __name__ == "__main__":
    unittest.main()
