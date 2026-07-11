"""Tests that ExternalAgentBroker injects the configured LLM API key/base
into the external agent's spawn env, without clobbering an operator's own
ANTHROPIC_API_KEY when no key is configured."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from opc.core.config import LLMConfig
from opc.layer3_agent.external_broker import ExternalAgentBroker
from opc.core.models import Task


def _make_broker(llm_config: LLMConfig) -> ExternalAgentBroker:
    broker = ExternalAgentBroker(
        store=AsyncMock(),
        approval_engine=MagicMock(),
        task_preparer=None,
        communication=None,
    )
    broker._llm_config_provider = lambda: llm_config
    return broker


class ExternalBrokerLLMEnvTests(unittest.TestCase):
    def test_llm_env_vars_added_when_key_configured(self) -> None:
        broker = _make_broker(LLMConfig(api_key="sk-configured", api_base="https://proxy.example.com"))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-configured")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://proxy.example.com")

    def test_no_env_vars_added_when_key_not_configured(self) -> None:
        broker = _make_broker(LLMConfig(api_key="", api_base=""))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def test_no_provider_is_a_no_op(self) -> None:
        broker = ExternalAgentBroker(store=AsyncMock(), approval_engine=MagicMock())
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env, {})


if __name__ == "__main__":
    unittest.main()
