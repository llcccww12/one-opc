"""HTTP handlers for user registration and login (POST /api/register, /api/login)."""

from __future__ import annotations

import aiohttp.web

from opc.plugins.office_ui.user_store import UserStore


async def _parse_credentials(request: aiohttp.web.Request) -> tuple[str, str] | aiohttp.web.Response:
    try:
        body = await request.json()
    except Exception:
        return aiohttp.web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    username = str(body.get("username") or "").strip()
    invite_code = str(body.get("invite_code") or "").strip()
    if not username or not invite_code:
        return aiohttp.web.json_response({"ok": False, "error": "missing_fields"}, status=400)
    return username, invite_code


def make_register_handler(user_store: UserStore):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        parsed = await _parse_credentials(request)
        if isinstance(parsed, aiohttp.web.Response):
            return parsed
        username, invite_code = parsed
        user_id, error = await user_store.register(username, invite_code)
        if error is not None:
            return aiohttp.web.json_response({"ok": False, "error": error}, status=400)
        token = await user_store.create_session(user_id)
        return aiohttp.web.json_response({"ok": True, "token": token, "user_id": user_id})

    return _handle


def make_login_handler(user_store: UserStore):
    async def _handle(request: aiohttp.web.Request) -> aiohttp.web.Response:
        parsed = await _parse_credentials(request)
        if isinstance(parsed, aiohttp.web.Response):
            return parsed
        username, invite_code = parsed
        user_id = await user_store.authenticate(username, invite_code)
        if user_id is None:
            return aiohttp.web.json_response({"ok": False, "error": "invalid_credentials"}, status=401)
        token = await user_store.create_session(user_id)
        return aiohttp.web.json_response({"ok": True, "token": token, "user_id": user_id})

    return _handle
