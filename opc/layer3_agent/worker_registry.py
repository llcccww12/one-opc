"""In-memory registry of connected opc-worker WebSocket connections, keyed by
user_id, plus request/response multiplexing for run_task dispatch.

Constructed once by OPCEngine and shared by both the office-UI plugin's
/worker/ws route handler (registers connections, forwards incoming messages)
and ExternalAgentBroker (dispatches tasks to a connected user's worker).
Cleared on process restart — workers reconnect and re-register.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class WorkerTaskOutcome:
    returncode: int
    stdout: str
    stderr: str
    resume_session_id: str | None


class _PendingRequest:
    def __init__(self, on_progress: Callable[[str], Awaitable[None]] | None) -> None:
        self.on_progress = on_progress
        self.future: asyncio.Future[WorkerTaskOutcome] = asyncio.get_running_loop().create_future()


class WorkerConnectionRegistry:
    def __init__(self) -> None:
        self._connections: dict[str, Any] = {}
        self._pending: dict[str, _PendingRequest] = {}

    def register(self, user_id: str, connection: Any) -> None:
        self._connections[user_id] = connection

    def unregister(self, user_id: str) -> None:
        self._connections.pop(user_id, None)

    def is_connected(self, user_id: str) -> bool:
        return user_id in self._connections

    async def dispatch_run_task(
        self,
        user_id: str,
        task_id: str,
        message: dict[str, Any],
        on_progress: Callable[[str], Awaitable[None]] | None,
        timeout_seconds: float,
    ) -> WorkerTaskOutcome | None:
        connection = self._connections.get(user_id)
        if connection is None:
            return None

        pending = _PendingRequest(on_progress)
        self._pending[task_id] = pending
        try:
            await connection.send_json(message)
            try:
                return await asyncio.wait_for(pending.future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                return None
        finally:
            self._pending.pop(task_id, None)

    async def handle_worker_message(self, message: dict[str, Any]) -> None:
        task_id = message.get("task_id")
        pending = self._pending.get(task_id) if task_id else None
        if pending is None:
            return

        msg_type = message.get("type")
        if msg_type == "progress" and pending.on_progress is not None:
            await pending.on_progress(str(message.get("text") or ""))
        elif msg_type == "task_complete":
            if not pending.future.done():
                pending.future.set_result(
                    WorkerTaskOutcome(
                        returncode=int(message.get("returncode", 1)),
                        stdout=str(message.get("stdout") or ""),
                        stderr=str(message.get("stderr") or ""),
                        resume_session_id=message.get("resume_session_id"),
                    )
                )

    async def send_cancel(self, user_id: str, task_id: str) -> None:
        connection = self._connections.get(user_id)
        if connection is not None:
            await connection.send_json({"type": "cancel_task", "task_id": task_id})
