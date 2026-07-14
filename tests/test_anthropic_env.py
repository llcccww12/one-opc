"""Unit tests for the shared BYOK-credential-to-env-var mapping."""

from __future__ import annotations

import unittest

from opc.layer3_agent.anthropic_env import anthropic_env_for


class AnthropicEnvTests(unittest.TestCase):
    def test_first_party_key_without_base_uses_api_key_header(self) -> None:
        env = anthropic_env_for("sk-first-party", "")
        self.assertEqual(env, {"ANTHROPIC_API_KEY": "sk-first-party"})

    def test_relay_key_with_base_uses_auth_token_header(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://relay.example.com")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-relay-key")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_relay_with_default_model_strips_provider_prefix(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com", "anthropic/mimo-v2.5-pro")
        self.assertEqual(env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    def test_relay_with_unprefixed_default_model_passes_through(self) -> None:
        env = anthropic_env_for("sk-relay-key", "https://relay.example.com", "mimo-v2.5-pro")
        self.assertEqual(env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    def test_no_key_produces_empty_env(self) -> None:
        env = anthropic_env_for("", "")
        self.assertEqual(env, {})

    def test_base_without_key_sets_base_only(self) -> None:
        env = anthropic_env_for("", "https://relay.example.com")
        self.assertEqual(env, {"ANTHROPIC_BASE_URL": "https://relay.example.com"})


if __name__ == "__main__":
    unittest.main()
