"""Unit tests for SettingsService's global LLM config read/write."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from opc.core.config import OPCConfig
from opc.plugins.office_ui.services.context import ModeState, OfficeServiceContext
from opc.plugins.office_ui.services.settings import SettingsService


def _build_context() -> OfficeServiceContext:
    config = OPCConfig()
    engine = SimpleNamespace(config=config, opc_home=SimpleNamespace())
    return OfficeServiceContext(
        engine=engine,
        agent_store=MagicMock(),
        chat_store=MagicMock(),
        event_adapter=MagicMock(),
        mode_state=ModeState(),
    )


class SettingsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_llm_config_reports_key_set_without_leaking_the_value(self) -> None:
        context = _build_context()
        context.engine.config.llm.api_key = "sk-secret"
        context.engine.config.llm.default_model = "anthropic/claude-sonnet-4-20250514"
        service = SettingsService(context)

        result = await service.get_llm_config()

        self.assertEqual(result.payload["default_model"], "anthropic/claude-sonnet-4-20250514")
        self.assertTrue(result.payload["api_key_set"])
        self.assertNotIn("api_key", result.payload)

    async def test_update_llm_config_persists_and_rebinds(self) -> None:
        context = _build_context()
        service = SettingsService(context)

        with patch.object(OPCConfig, "save") as save_mock:
            result = await service.update_llm_config({
                "default_model": "anthropic/claude-opus-4-1",
                "api_base": "https://proxy.example.com",
                "api_key": "sk-new-key",
            })

        save_mock.assert_called_once()
        self.assertEqual(context.engine.config.llm.default_model, "anthropic/claude-opus-4-1")
        self.assertEqual(context.engine.config.llm.api_base, "https://proxy.example.com")
        self.assertEqual(context.engine.config.llm.api_key, "sk-new-key")
        self.assertTrue(result.payload["api_key_set"])

    async def test_update_llm_config_blank_api_key_does_not_clear_existing_key(self) -> None:
        context = _build_context()
        context.engine.config.llm.api_key = "sk-existing"
        service = SettingsService(context)

        with patch.object(OPCConfig, "save"):
            await service.update_llm_config({"default_model": "anthropic/claude-opus-4-1", "api_key": ""})

        self.assertEqual(context.engine.config.llm.api_key, "sk-existing")


if __name__ == "__main__":
    unittest.main()
