from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from opc.core.config import LLMConfig
from opc.llm.provider import LLMProvider


class TestLLMProviderHasCredentials(unittest.TestCase):
    def test_configured_api_key_has_credentials(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o", api_key="sk-real"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(provider.has_credentials())

    def test_api_key_env_resolves_to_credentials(self) -> None:
        with patch.dict(os.environ, {"MY_KEY": "sk-env"}, clear=True):
            provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o", api_key_env="MY_KEY"))
            self.assertTrue(provider.has_credentials())

    def test_no_key_anywhere_has_no_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o", api_key=""))
            self.assertFalse(provider.has_credentials())

    def test_well_known_env_var_counts_as_credentials(self) -> None:
        """Users who export OPENAI_API_KEY without putting it in config are not downgraded."""
        provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o", api_key=""))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}, clear=True):
            self.assertTrue(provider.has_credentials())


class TestLLMProviderContextWindow(unittest.TestCase):
    def test_gpt_5_4_override_applies_on_official_openai_base(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="openai/gpt-5.4"))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={"max_input_tokens": 128000}):
            self.assertEqual(provider.get_context_window(), 1_050_000)

    def test_gpt_5_4_override_does_not_apply_on_proxy_base(self) -> None:
        provider = LLMProvider(LLMConfig(
            default_model="openai/gpt-5.4",
            api_base="https://openrouter.ai/api/v1",
        ))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={"max_input_tokens": 128000}):
            self.assertEqual(provider.get_context_window(), 128000)

    def test_poe_claude_sonnet_4_5_model_uses_local_context_window(self) -> None:
        provider = LLMProvider(LLMConfig(
            default_model="claude-sonnet-4.5",
            api_base="https://api.poe.com/v1",
        ))

        with patch("opc.llm.provider.litellm.get_model_info") as get_model_info:
            self.assertEqual(provider.get_context_window(), 64_000)
            get_model_info.assert_not_called()

    def test_poe_openai_compatible_legacy_prefix_uses_same_context_window(self) -> None:
        provider = LLMProvider(LLMConfig(
            default_model="openai/claude-sonnet-4.5",
            api_base="https://api.poe.com/v1",
        ))

        with patch("opc.llm.provider.litellm.get_model_info") as get_model_info:
            self.assertEqual(provider.get_context_window(), 64_000)
            get_model_info.assert_not_called()

    def test_non_overridden_model_still_uses_litellm(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o"))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={"max_input_tokens": 128000}):
            self.assertEqual(provider.get_context_window(), 128000)

    def test_context_window_uses_max_input_tokens_not_output_cap(self) -> None:
        """deepseek-style entries: max_tokens is the OUTPUT cap (8192), the
        context window is max_input_tokens (1M). The window must not be 8192."""
        provider = LLMProvider(LLMConfig(default_model="deepseek/deepseek-v4-pro"))

        with patch(
            "opc.llm.provider.litellm.get_model_info",
            return_value={"max_input_tokens": 1_000_000, "max_tokens": 8192, "max_output_tokens": 8192},
        ):
            self.assertEqual(provider.get_context_window(), 1_000_000)

    def test_config_scalar_override_supplies_window_for_unmapped_model(self) -> None:
        """Unmapped proxy models (doubao/minimax/…) get a real window from config."""
        provider = LLMProvider(LLMConfig(
            default_model="openai/doubao-seed-2.0-pro",
            api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
            context_window=256000,
        ))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={}) as get_model_info:
            self.assertEqual(provider.get_context_window(), 256000)
            get_model_info.assert_not_called()

    def test_unmapped_model_without_override_falls_back_to_default(self) -> None:
        """No override + litellm can't map → 128000 fallback, not None."""
        provider = LLMProvider(LLMConfig(
            default_model="openai/doubao-seed-2.0-pro",
            api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        ))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={}):
            self.assertEqual(provider.get_context_window(), 128000)

    def test_unmapped_model_litellm_error_falls_back_to_default(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="deepseek/deepseek-v4-pro"))

        with patch(
            "opc.llm.provider.litellm.get_model_info",
            side_effect=Exception("Model deepseek-v4-pro isn't mapped yet."),
        ):
            self.assertEqual(provider.get_context_window(), 128000)

    def test_config_per_model_override_takes_precedence(self) -> None:
        provider = LLMProvider(LLMConfig(
            default_model="openai/doubao-seed-2.0-pro",
            context_window=200000,
            context_window_overrides={"doubao-seed-2.0-pro": 262144},
        ))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={}):
            self.assertEqual(provider.get_context_window(), 262144)

    def test_config_override_wins_over_litellm_for_mapped_model(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="openai/gpt-4o", context_window=50000))

        with patch("opc.llm.provider.litellm.get_model_info", return_value={"max_input_tokens": 128000}) as get_model_info:
            self.assertEqual(provider.get_context_window(), 50000)
            get_model_info.assert_not_called()


def _fake_completion_response(content: str = "hi") -> SimpleNamespace:
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content, tool_calls=None))],
    )


class TestLLMProviderTemperatureFallback(unittest.TestCase):
    """Some Bedrock-hosted Claude models (extended thinking always on) reject
    any temperature != 1. chat()/chat_stream() should retry once at temperature=1
    and remember the model so later calls skip the failing round trip."""

    _TEMPERATURE_ERROR = Exception(
        "litellm.BadRequestError: AnthropicException - "
        'b\'{"error":{"type":"aws_invoke_error","message":"ValidationException: '
        "`temperature` is deprecated for this model.\"},\"type\":\"error\"}'"
    )

    def test_retries_with_temperature_1_when_model_rejects_temperature(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="claude-sonnet-5", temperature=0.3))
        mock_acompletion = AsyncMock(side_effect=[self._TEMPERATURE_ERROR, _fake_completion_response()])

        with patch("opc.llm.provider.litellm.acompletion", mock_acompletion), \
             patch("opc.llm.provider.litellm.get_model_info", return_value={}):
            result = asyncio.run(provider.chat(messages=[{"role": "user", "content": "hi"}]))

        self.assertEqual(result["content"], "hi")
        self.assertEqual(mock_acompletion.call_count, 2)
        self.assertEqual(mock_acompletion.call_args_list[0].kwargs["temperature"], 0.3)
        self.assertEqual(mock_acompletion.call_args_list[1].kwargs["temperature"], 1)
        self.assertIn("claude-sonnet-5", provider._temperature_unsupported_models)

    def test_remembered_model_skips_straight_to_temperature_1(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="claude-sonnet-5", temperature=0.3))
        provider._temperature_unsupported_models.add("claude-sonnet-5")
        mock_acompletion = AsyncMock(return_value=_fake_completion_response())

        with patch("opc.llm.provider.litellm.acompletion", mock_acompletion), \
             patch("opc.llm.provider.litellm.get_model_info", return_value={}):
            asyncio.run(provider.chat(messages=[{"role": "user", "content": "hi"}]))

        self.assertEqual(mock_acompletion.call_count, 1)
        self.assertEqual(mock_acompletion.call_args.kwargs["temperature"], 1)

    def test_unrelated_error_is_not_retried(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="claude-sonnet-5", temperature=0.3))
        mock_acompletion = AsyncMock(side_effect=Exception("litellm.RateLimitError: too many requests"))

        with patch("opc.llm.provider.litellm.acompletion", mock_acompletion), \
             patch("opc.llm.provider.litellm.get_model_info", return_value={}):
            with self.assertRaises(Exception):
                asyncio.run(provider.chat(messages=[{"role": "user", "content": "hi"}]))

        self.assertEqual(mock_acompletion.call_count, 1)
        self.assertEqual(provider._temperature_unsupported_models, set())


if __name__ == "__main__":
    unittest.main()
