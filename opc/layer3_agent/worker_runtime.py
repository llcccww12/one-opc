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
import base64
import json
import shutil
from pathlib import Path
from typing import Any

import aiohttp

from opc.layer3_agent.adapters.claude_code import ClaudeCodeAdapter
from opc.layer3_agent.anthropic_env import anthropic_env_for

_RECONNECT_DELAY_SECONDS = 5


def _resolve_safe_path(workspace_root: Path, relative_path: str) -> Path:
    """Resolve relative_path under workspace_root, rejecting any path that
    would escape it (path traversal, absolute paths, symlinks pointing
    outward). Every worker-side file operation MUST go through this."""
    candidate = (workspace_root / relative_path).resolve()
    root = workspace_root.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("path escapes workspace root")
    return candidate


def _is_safe_project_id(project_id: str) -> bool:
    """A project_id must be a single path segment: no separators, no empty
    string, and not '.'/'..'. Callers join it directly onto the workspace
    root before _resolve_safe_path even runs, so a bad project_id would
    otherwise let the path-traversal check validate against the wrong root."""
    return project_id not in ("", ".", "..") and "/" not in project_id and "\\" not in project_id


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
        elif msg_type == "list_dir":
            await self._handle_list_dir(ws, data)
        elif msg_type == "read_file":
            await self._handle_read_file(ws, data)
        elif msg_type == "delete_file":
            await self._handle_delete_file(ws, data)

    async def _handle_run_task(self, ws: Any, data: dict) -> None:
        task_id = str(data.get("task_id") or "")
        project_id = str(data.get("project_id") or "default")
        cmd = list(data.get("cmd") or [])
        api_key = str(data.get("api_key") or "")
        api_base = str(data.get("api_base") or "")
        default_model = str(data.get("default_model") or "")

        workspace_path = self._workspace_root / project_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        extra_env = anthropic_env_for(api_key, api_base, default_model)
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

    async def _handle_list_dir(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        project_id = str(data.get("project_id") or "default")
        if not _is_safe_project_id(project_id):
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": "invalid_path"})
            return
        workspace_path = self._workspace_root / project_id
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": "invalid_path"})
            return

        if not target.exists() or not target.is_dir():
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": "not_found"})
            return

        try:
            entries = []
            for child in sorted(target.iterdir()):
                stat_result = child.stat()
                entries.append({
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": stat_result.st_size,
                    "mtime": stat_result.st_mtime,
                })
        except OSError as exc:
            await ws.send_json({"type": "dir_listing", "request_id": request_id, "error": str(exc)})
            return
        await ws.send_json({"type": "dir_listing", "request_id": request_id, "entries": entries})

    async def _handle_read_file(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        project_id = str(data.get("project_id") or "default")
        if not _is_safe_project_id(project_id):
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": "invalid_path"})
            return
        workspace_path = self._workspace_root / project_id
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": "invalid_path"})
            return

        if not target.exists() or not target.is_file():
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": "not_found"})
            return

        try:
            content_bytes = target.read_bytes()
        except OSError as exc:
            await ws.send_json({"type": "file_content", "request_id": request_id, "error": str(exc)})
            return
        await ws.send_json({
            "type": "file_content",
            "request_id": request_id,
            "content_base64": base64.b64encode(content_bytes).decode("ascii"),
        })

    async def _handle_delete_file(self, ws: Any, data: dict) -> None:
        request_id = str(data.get("request_id") or "")
        project_id = str(data.get("project_id") or "default")
        if not _is_safe_project_id(project_id):
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": "invalid_path"})
            return
        workspace_path = self._workspace_root / project_id
        try:
            target = _resolve_safe_path(workspace_path, str(data.get("path") or ""))
        except ValueError:
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": "invalid_path"})
            return

        if not target.exists():
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": "not_found"})
            return

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": False, "error": str(exc)})
            return

        await ws.send_json({"type": "delete_result", "request_id": request_id, "ok": True})
