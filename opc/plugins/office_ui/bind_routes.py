"""HTTP handlers for per-user SkyPilot VM binding (POST /api/vm/bind, GET /api/vm/status)."""

from __future__ import annotations

import aiohttp.web

from opc.plugins.office_ui.tenant_vm_service import TenantVmService
from opc.plugins.office_ui.user_store import UserStore


async def _authenticate_bearer(request: aiohttp.web.Request, user_store: UserStore) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    if not token:
        return None
    return await user_store.get_user_id_for_token(token)


def make_bind_vm_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.bind(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle


def make_vm_status_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.get_status(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle


def make_vm_stop_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.stop_vm(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle


def make_vm_start_handler(user_store: UserStore, vm_service: TenantVmService):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id = await _authenticate_bearer(request, user_store)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        status = await vm_service.start_vm(user_id)
        return aiohttp.web.json_response({"ok": True, **status})

    return _handle
