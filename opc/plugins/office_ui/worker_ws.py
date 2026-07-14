"""WebSocket endpoint for opc worker connections (outbound from tenant VMs).

Separate from the browser-facing /ws endpoint handled by WSHandler: different
auth (a VM's own tenant_vms.auth_token, not a user session token) and a
narrower, non-browser-facing message protocol (run_task/progress/
task_complete/cancel_task) documented in
docs/superpowers/specs/2026-07-14-opc-worker-runtime-mode-design.md.
"""

from __future__ import annotations

import aiohttp.web

from opc.layer3_agent.worker_registry import WorkerConnectionRegistry
from opc.plugins.office_ui.tenant_vm_store import TenantVmStore


def make_worker_ws_handler(vm_store: TenantVmStore, worker_registry: WorkerConnectionRegistry):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        token = request.query.get("token", "")
        user_id = await vm_store.get_user_id_for_auth_token(token) if token else None

        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)
        if user_id is None:
            await ws.close(code=4401, message=b"unauthorized")
            return ws

        worker_registry.register(user_id, ws)
        try:
            async for msg in ws:
                if msg.type == aiohttp.web.WSMsgType.TEXT:
                    try:
                        data = msg.json()
                    except Exception:
                        continue
                    await worker_registry.handle_worker_message(data)
        finally:
            worker_registry.unregister(user_id)
        return ws

    return _handle
