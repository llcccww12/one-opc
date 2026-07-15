"""Tests for ExternalAgentBroker's worker-relay dispatch branch: when the
task's project owner has a connected worker, route through it instead of
the local subprocess path — and never silently fall back to local execution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from opc.core.models import Task, TaskStatus
from opc.layer3_agent.external_broker import ExternalAgentBroker
from opc.layer3_agent.worker_registry import WorkerTaskOutcome


def _make_broker(llm_config_provider=None) -> ExternalAgentBroker:
    return ExternalAgentBroker(
        store=AsyncMock(), approval_engine=MagicMock(), llm_config_provider=llm_config_provider
    )


def _make_task(project_id: str = "demo") -> Task:
    return Task(id="task-1", session_id="s1", title="t", description="d", project_id=project_id)


class RunViaWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_failed_result_when_relay_not_configured(self) -> None:
        broker = _make_broker()
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)

    async def test_returns_failed_result_when_owner_cannot_be_resolved(self) -> None:
        broker = _make_broker()
        broker.configure_worker_relay(
            worker_registry=MagicMock(),
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value=None),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("未连接", result.content)

    async def test_returns_failed_result_when_worker_not_connected(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = False
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        registry.dispatch_run_task.assert_not_called()

    async def test_returns_failed_result_when_credentials_missing(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=None),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("API Key", result.content)
        registry.dispatch_run_task.assert_not_called()

    async def test_successful_dispatch_returns_done_result_with_resume_id(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(
            return_value=WorkerTaskOutcome(returncode=0, stdout="hi there", stderr="", resume_session_id="sess-1")
        )
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "https://relay.example.com")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={"session_id": "s1"}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.DONE)
        self.assertEqual(result.content, "hi there")
        self.assertEqual(result.artifacts["resume_session_id"], "sess-1")
        self.assertEqual(result.artifacts["session_id"], "s1")  # metadata preserved

        sent_message = registry.dispatch_run_task.await_args.args[2]
        self.assertEqual(sent_message["api_key"], "sk-x")
        self.assertEqual(sent_message["api_base"], "https://relay.example.com")
        self.assertEqual(sent_message["cmd"], ["claude"])
        self.assertEqual(sent_message["default_model"], "")  # no llm_config_provider configured

    async def test_dispatch_includes_platform_default_model_for_relay(self) -> None:
        # default_model is a platform-wide setting (not per-user BYOK) — same
        # source _apply_llm_config_env already uses for the local-execution
        # path — so a relay-pointed BYOK user still gets a model name the
        # relay understands instead of Claude Code's own default alias.
        broker = _make_broker(
            llm_config_provider=lambda: SimpleNamespace(default_model="anthropic/mimo-v2.5-pro")
        )
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(
            return_value=WorkerTaskOutcome(returncode=0, stdout="ok", stderr="", resume_session_id=None)
        )
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "https://relay.example.com")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        sent_message = registry.dispatch_run_task.await_args.args[2]
        self.assertEqual(sent_message["default_model"], "anthropic/mimo-v2.5-pro")

    async def test_nonzero_returncode_produces_failed_result(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(
            return_value=WorkerTaskOutcome(returncode=1, stdout="", stderr="boom", resume_session_id=None)
        )
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertEqual(result.artifacts["stderr"], "boom")

    async def test_dispatch_timeout_produces_failed_result(self) -> None:
        broker = _make_broker()
        registry = MagicMock()
        registry.is_connected.return_value = True
        registry.dispatch_run_task = AsyncMock(return_value=None)
        broker.configure_worker_relay(
            worker_registry=registry,
            credential_provider=AsyncMock(return_value=("sk-x", "")),
            owner_resolver=AsyncMock(return_value="user-1"),
        )
        result = await broker._run_via_worker(
            adapter=MagicMock(), task=_make_task(), workspace_path="/tmp", cmd=["claude"],
            metadata={}, on_progress=None,
        )
        self.assertEqual(result.status, TaskStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
