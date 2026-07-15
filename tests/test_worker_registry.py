"""Unit tests for WorkerConnectionRegistry's connection tracking and
run_task request/response multiplexing."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry


class WorkerConnectionRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_is_connected_false_when_unregistered(self) -> None:
        registry = WorkerConnectionRegistry()
        self.assertFalse(registry.is_connected("user-1"))

    async def test_register_then_is_connected_true(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        self.assertTrue(registry.is_connected("user-1"))

    async def test_unregister_clears_connection(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        registry.unregister("user-1")
        self.assertFalse(registry.is_connected("user-1"))

    async def test_dispatch_run_task_returns_none_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        result = await registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=1)
        self.assertIsNone(result)

    async def test_dispatch_run_task_sends_message_and_waits_for_completion(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=5)
        )
        await asyncio.sleep(0)  # let dispatch_run_task register the pending future
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "hello", "stderr": "", "resume_session_id": "sess-abc",
        })
        outcome = await dispatch_task

        connection.send_json.assert_awaited_once_with({"type": "run_task"})
        self.assertEqual(outcome.returncode, 0)
        self.assertEqual(outcome.stdout, "hello")
        self.assertEqual(outcome.resume_session_id, "sess-abc")

    async def test_dispatch_run_task_forwards_progress_messages(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        received: list[str] = []

        async def _on_progress(text: str) -> None:
            received.append(text)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, _on_progress, timeout_seconds=5)
        )
        await asyncio.sleep(0)
        await registry.handle_worker_message({"type": "progress", "task_id": "task-1", "text": "line one"})
        await registry.handle_worker_message({"type": "progress", "task_id": "task-1", "text": "line two"})
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "", "stderr": "", "resume_session_id": None,
        })
        await dispatch_task

        self.assertEqual(received, ["line one", "line two"])

    async def test_dispatch_run_task_times_out_when_no_response(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        result = await registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=0.05)
        self.assertIsNone(result)

    async def test_send_cancel_sends_cancel_message(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)
        await registry.send_cancel("user-1", "task-1")
        connection.send_json.assert_awaited_once_with({"type": "cancel_task", "task_id": "task-1"})

    async def test_send_cancel_is_a_noop_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        await registry.send_cancel("user-1", "task-1")  # must not raise

    async def test_dispatch_request_returns_none_when_not_connected(self) -> None:
        registry = WorkerConnectionRegistry()
        result = await registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=1)
        self.assertIsNone(result)

    async def test_dispatch_request_sends_message_and_returns_raw_response(self) -> None:
        registry = WorkerConnectionRegistry()
        connection = AsyncMock()
        registry.register("user-1", connection)

        dispatch_task = asyncio.ensure_future(
            registry.dispatch_request("user-1", "req-1", {"type": "list_dir", "request_id": "req-1"}, timeout_seconds=5)
        )
        await asyncio.sleep(0)
        await registry.handle_worker_message({"type": "dir_listing", "request_id": "req-1", "entries": []})
        response = await dispatch_task

        connection.send_json.assert_awaited_once_with({"type": "list_dir", "request_id": "req-1"})
        self.assertEqual(response, {"type": "dir_listing", "request_id": "req-1", "entries": []})

    async def test_dispatch_request_times_out_when_no_response(self) -> None:
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())
        result = await registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=0.05)
        self.assertIsNone(result)

    async def test_dispatch_request_and_dispatch_run_task_do_not_interfere(self) -> None:
        """request_id-keyed and task_id-keyed multiplexing must be independent —
        a run_task in flight must not be resolved by a request_id-keyed reply
        and vice versa."""
        registry = WorkerConnectionRegistry()
        registry.register("user-1", AsyncMock())

        task_dispatch = asyncio.ensure_future(
            registry.dispatch_run_task("user-1", "task-1", {"type": "run_task"}, None, timeout_seconds=5)
        )
        request_dispatch = asyncio.ensure_future(
            registry.dispatch_request("user-1", "req-1", {"type": "list_dir"}, timeout_seconds=5)
        )
        await asyncio.sleep(0)

        await registry.handle_worker_message({"type": "dir_listing", "request_id": "req-1", "entries": []})
        await registry.handle_worker_message({
            "type": "task_complete", "task_id": "task-1", "returncode": 0,
            "stdout": "", "stderr": "", "resume_session_id": None,
        })

        request_result = await request_dispatch
        task_result = await task_dispatch
        self.assertEqual(request_result, {"type": "dir_listing", "request_id": "req-1", "entries": []})
        self.assertEqual(task_result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
