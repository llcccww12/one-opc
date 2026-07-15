"""Unit tests for WorkerRuntime's message handling (run_task/cancel_task).

These test _handle_run_task/_handle_cancel_task directly against a fake ws
and a mocked ClaudeCodeAdapter.start_process — the outer run_forever/
_connect_and_serve reconnect loop is real network plumbing, verified in the
end-to-end task instead of here."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from opc.layer3_agent.worker_runtime import WorkerRuntime


class _FakeStreamReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


def _make_fake_proc(stdout_lines: list[bytes], stderr_lines: list[bytes], returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.stdout = _FakeStreamReader(stdout_lines + [b""])
    proc.stderr = _FakeStreamReader(stderr_lines + [b""])
    proc.wait = AsyncMock(return_value=returncode)
    return proc


class WorkerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_task_streams_progress_and_completes(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        ws = AsyncMock()
        fake_proc = _make_fake_proc([b"line one\n", b"line two\n"], [], 0)

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process", AsyncMock(return_value=fake_proc)
        ), patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.extract_resume_session_id", return_value="sess-123"
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "demo", "cmd": ["claude", "--print"],
                "api_key": "sk-test", "api_base": "",
            })

        sent = [call.args[0] for call in ws.send_json.await_args_list]
        progress_texts = [m["text"] for m in sent if m["type"] == "progress"]
        self.assertEqual(progress_texts, ["line one\n", "line two\n"])
        final = sent[-1]
        self.assertEqual(final["type"], "task_complete")
        self.assertEqual(final["returncode"], 0)
        self.assertEqual(final["resume_session_id"], "sess-123")
        self.assertEqual(final["stdout"], "line one\nline two\n")

    async def test_run_task_reports_spawn_failure_as_task_complete_with_nonzero_code(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        ws = AsyncMock()

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process",
            AsyncMock(side_effect=OSError("binary not found")),
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "demo", "cmd": ["claude"],
                "api_key": "sk-test", "api_base": "",
            })

        final = ws.send_json.await_args.args[0]
        self.assertEqual(final["type"], "task_complete")
        self.assertNotEqual(final["returncode"], 0)
        self.assertIn("binary not found", final["stderr"])

    async def test_run_task_creates_project_workspace_directory(self) -> None:
        workspace_root = Path(tempfile.mkdtemp())
        runtime = WorkerRuntime("http://localhost:8765", "tok", workspace_root)
        ws = AsyncMock()
        fake_proc = _make_fake_proc([], [], 0)

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process", AsyncMock(return_value=fake_proc)
        ), patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.extract_resume_session_id", return_value=None
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "my-project", "cmd": ["claude"],
                "api_key": "", "api_base": "",
            })

        self.assertTrue((workspace_root / "my-project").is_dir())

    async def test_run_task_passes_default_model_to_relay_env(self) -> None:
        # default_model must reach anthropic_env_for so a relay-pointed
        # api_base gets an ANTHROPIC_MODEL the relay understands, instead of
        # Claude Code's own default model alias.
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        ws = AsyncMock()
        fake_proc = _make_fake_proc([], [], 0)
        start_process = AsyncMock(return_value=fake_proc)

        with patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.start_process", start_process
        ), patch(
            "opc.layer3_agent.worker_runtime.ClaudeCodeAdapter.extract_resume_session_id", return_value=None
        ):
            await runtime._handle_run_task(ws, {
                "task_id": "task-1", "project_id": "demo", "cmd": ["claude"],
                "api_key": "sk-test", "api_base": "https://relay.example.com",
                "default_model": "anthropic/mimo-v2.5-pro",
            })

        _cmd, _workspace = start_process.await_args.args
        extra_env = start_process.await_args.kwargs["extra_env"]
        self.assertEqual(extra_env["ANTHROPIC_MODEL"], "mimo-v2.5-pro")

    async def test_cancel_task_kills_matching_process(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        fake_process = MagicMock()
        runtime._current_task_id = "task-1"
        runtime._current_process = fake_process
        runtime._handle_cancel_task({"task_id": "task-1"})
        fake_process.kill.assert_called_once()

    async def test_cancel_task_ignores_mismatched_task_id(self) -> None:
        runtime = WorkerRuntime("http://localhost:8765", "tok", Path(tempfile.mkdtemp()))
        fake_process = MagicMock()
        runtime._current_task_id = "task-1"
        runtime._current_process = fake_process
        runtime._handle_cancel_task({"task_id": "other-task"})
        fake_process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
