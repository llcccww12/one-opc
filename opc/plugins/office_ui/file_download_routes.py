"""HTTP handler for downloading a file from a user's VM workspace
(GET /api/vm/files/download?project_id=...&path=...).

Uses REST rather than a WS request type because file content doesn't belong
in a JSON WS message body — the response here streams a plain HTTP body.
"""

from __future__ import annotations

import base64
import secrets

import aiohttp.web

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.user_store import UserStore

_DOWNLOAD_TIMEOUT_SECONDS = 30


def make_file_download_handler(user_store: UserStore, worker_registry: WorkerConnectionRegistry):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.StreamResponse:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):].strip()
        else:
            token = str(request.query.get("token") or "")

        requesting_user_id = await user_store.get_user_id_for_token(token) if token else None
        if requesting_user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        project_id = str(request.query.get("project_id") or "")
        path = str(request.query.get("path") or "")
        owner_user_id = await user_store.get_project_owner(project_id)
        if not owner_user_id or owner_user_id != requesting_user_id:
            return aiohttp.web.json_response({"ok": False, "error": "forbidden"}, status=403)

        if not worker_registry.is_connected(owner_user_id):
            return aiohttp.web.json_response({"ok": False, "error": "worker_not_connected"}, status=409)

        request_id = secrets.token_hex(8)
        response = await worker_registry.dispatch_request(
            owner_user_id,
            request_id,
            {"type": "read_file", "request_id": request_id, "project_id": project_id, "path": path},
            timeout_seconds=_DOWNLOAD_TIMEOUT_SECONDS,
        )
        if response is None or response.get("error"):
            error = (response or {}).get("error", "timeout")
            return aiohttp.web.json_response({"ok": False, "error": error}, status=404)

        content = base64.b64decode(response["content_base64"])
        filename = path.rsplit("/", 1)[-1] or "download"
        return aiohttp.web.Response(
            body=content,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return _handle
