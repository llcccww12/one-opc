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
    def test_custom_base_url_sets_api_key_and_base_url(self) -> None:
        # Claude Code CLI only reads ANTHROPIC_API_KEY, so always set it
        # even when api_base is configured (custom relay).
        broker = _make_broker(LLMConfig(api_key="sk-configured", api_base="https://proxy.example.com"))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-configured")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://proxy.example.com")

    def test_custom_base_url_sets_model_stripping_litellm_prefix(self) -> None:
        # A custom relay speaks its own model name, not a "claude-*" alias —
        # ANTHROPIC_MODEL must be derived from default_model with the
        # litellm-style "anthropic/" provider prefix stripped.
        broker = _make_broker(
            LLMConfig(
                api_key="sk-configured",
                api_base="https://proxy.example.com",
                default_model="anthropic/mimo-v2.5-pro",
            )
        )
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    def test_api_key_used_when_no_custom_base_url(self) -> None:
        # No custom api_base configured means the official Anthropic API,
        # which expects the key via the x-api-key scheme (ANTHROPIC_API_KEY).
        broker = _make_broker(LLMConfig(api_key="sk-configured", api_base=""))
        env: dict[str, str] = {}
        broker._apply_llm_config_env(env)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-configured")
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

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
