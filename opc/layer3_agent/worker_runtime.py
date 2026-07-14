"""opc worker runtime: connects outbound to the control plane, receives
run_task/cancel_task messages, spawns Claude Code CLI locally via the
existing ClaudeCodeAdapter, and streams progress/results back.

Runs inside a user's SkyPilot VM (sub-project 1) — never on the control
plane. Reuses layer3_agent adapter code so file/tool operations happen on
this machine's local disk, not proxied from the control plane. The control
plane already built the full `cmd` argv (including any --resume <id> flag)
before sending run_task — this runtime executes it verbatim, it does not
rebuild session-resume arguments itself.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

from opc.layer3_agent.adapters.claude_code import ClaudeCodeAdapter
from opc.layer3_agent.anthropic_env import anthropic_env_for

_RECONNECT_DELAY_SECONDS = 5


class WorkerRuntime:
    def __init__(self, control_plane_url: str, worker_token: str, workspace_root: Path) -> None:
        self._control_plane_url = control_plane_url.rstrip("/")
        self._worker_token = worker_token
        self._workspace_root = workspace_root
        self._current_task_id: str | None = None
        self._current_process: Any = None

    async def run_forever(self) -> None:
        while True:
            try:
                await self._connect_and_serve()
            except (aiohttp.ClientError, ConnectionError, OSError):
                pass
            await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _connect_and_serve(self) -> None:
        url = f"{self._control_plane_url}/worker/ws?token={self._worker_token}"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                await ws.send_json({"type": "hello"})
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        continue
                    await self._handle_message(ws, data)

    async def _handle_message(self, ws: Any, data: dict) -> None:
        msg_type = data.get("type")
        if msg_type == "run_task":
            await self._handle_run_task(ws, data)
        elif msg_type == "cancel_task":
            self._handle_cancel_task(data)

    async def _handle_run_task(self, ws: Any, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        project_id = str(data.get("project_id") or "default")
        cmd = list(data.get("cmd") or [])
        api_key = str(data.get("api_key") or "")
        api_base = str(data.get("api_base") or "")

        workspace_path = self._workspace_root / project_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        extra_env = anthropic_env_for(api_key, api_base)
        adapter = ClaudeCodeAdapter()

        self._current_task_id = task_id
        try:
            proc = await adapter.start_process(cmd, str(workspace_path), extra_env=extra_env)
        except OSError as exc:
            await ws.send_json({
                "type": "task_complete", "task_id": task_id, "returncode": 1,
                "stdout": "", "stderr": f"spawn failed: {exc}", "resume_session_id": None,
            })
            self._current_task_id = None
            return

        self._current_process = proc
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _drain(stream: Any, sink: list[str], stream_name: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                sink.append(text)
                await ws.send_json({"type": "progress", "task_id": task_id, "stream": stream_name, "text": text})

        await asyncio.gather(
            _drain(proc.stdout, stdout_chunks, "stdout"),
            _drain(proc.stderr, stderr_chunks, "stderr"),
        )
        returncode = await proc.wait()

        output = "".join(stdout_chunks)
        resume_session_id = adapter.extract_resume_session_id(output)

        await ws.send_json({
            "type": "task_complete",
            "task_id": task_id,
            "returncode": returncode,
            "stdout": output,
            "stderr": "".join(stderr_chunks),
            "resume_session_id": resume_session_id,
        })
        self._current_task_id = None
        self._current_process = None

    def _handle_cancel_task(self, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        if task_id and task_id == self._current_task_id and self._current_process is not None:
            self._current_process.kill()
