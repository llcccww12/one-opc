"""Tests that ClaudeCodeAdapter.build_process_env strips the developer's own
personal Anthropic/Claude Code auth and session-identity env vars, so the
platform's own configured LLM provider (e.g. a third-party relay set via
ExternalAgentBroker._apply_llm_config_env) is always authoritative for the
spawned `claude` subprocess."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from opc.core.config import ExternalAgentConfig
from opc.core.models import Task
from opc.layer3_agent.adapters.claude_code import ClaudeCodeAdapter


class ClaudeCodeAdapterEnvTests(unittest.TestCase):
    def test_strips_inherited_personal_auth_and_session_vars(self) -> None:
        leaked_parent_env = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-personal-leaked",
            "ANTHROPIC_AUTH_TOKEN": "personal-bearer-leaked",
            "ANTHROPIC_BASE_URL": "https://personal-relay.example.com",
            "ANTHROPIC_MODEL": "claude-sonnet-5",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "arn:aws:bedrock:us-east-1:1:x",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "parent-session",
        }
        adapter = ClaudeCodeAdapter()
        with patch(
            "opc.layer3_agent.adapters.claude_code.os.environ",
            leaked_parent_env,
        ):
            env = adapter.build_process_env(
                {"ANTHROPIC_AUTH_TOKEN": "mimo-token", "ANTHROPIC_BASE_URL": "https://mimo.example.com"}
            )

        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "mimo-token")
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://mimo.example.com")
        self.assertNotIn("ANTHROPIC_MODEL", env)
        self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_no_extra_env_still_strips_leaked_vars(self) -> None:
        leaked_parent_env = {
            "PATH": "/usr/bin",
            "ANTHROPIC_API_KEY": "sk-personal-leaked",
        }
        adapter = ClaudeCodeAdapter()
        with patch(
            "opc.layer3_agent.adapters.claude_code.os.environ",
            leaked_parent_env,
        ):
            env = adapter.build_process_env(None)

        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["PATH"], "/usr/bin")


class ClaudeCodeAdapterSettingSourcesTests(unittest.TestCase):
    """`~/.claude/settings.json` (the "user" setting source) can carry the
    developer's own personal `model`/`env` overrides for their everyday
    interactive Claude Code use. Claude Code loads it unconditionally, so it
    silently outranks whatever ANTHROPIC_AUTH_TOKEN/BASE_URL/MODEL this
    adapter injects via subprocess env — sending OpenOPC's automated task to
    the developer's own account/model instead of the platform's configured
    one. `--setting-sources project,local` (excluding "user") is Claude
    Code's documented mechanism to prevent that."""

    def test_build_invocation_excludes_user_settings(self) -> None:
        adapter = ClaudeCodeAdapter(config=ExternalAgentConfig(command="claude"))
        cmd, _ = adapter.build_invocation(Task(title="demo"), workspace_path=None)
        self.assertIn("--setting-sources", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project,local")

    def test_build_interactive_invocation_excludes_user_settings(self) -> None:
        adapter = ClaudeCodeAdapter(config=ExternalAgentConfig(command="claude"))
        cmd, _ = adapter.build_interactive_invocation(Task(title="demo"), workspace_path=None)
        self.assertIn("--setting-sources", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project,local")

    def test_does_not_duplicate_user_supplied_setting_sources(self) -> None:
        adapter = ClaudeCodeAdapter(
            config=ExternalAgentConfig(command="claude", extra_args=["--setting-sources", "user"])
        )
        cmd, _ = adapter.build_invocation(Task(title="demo"), workspace_path=None)
        self.assertEqual(cmd.count("--setting-sources"), 1)


if __name__ == "__main__":
    unittest.main()
