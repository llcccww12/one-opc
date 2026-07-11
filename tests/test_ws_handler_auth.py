"""Unit tests for WSHandler's token-based WS authentication hook."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from opc.plugins.office_ui.ws_handler import WSHandler


class _FakeRequest:
    def __init__(self, token: str | None) -> None:
        self.query = {"token": token} if token is not None else {}


class WSHandlerAuthTests(unittest.IsolatedAsyncioTestCase):
    def _make_handler(self, user_store) -> WSHandler:
        handler = object.__new__(WSHandler)
        handler._user_store = user_store
        return handler

    async def test_no_user_store_allows_connection(self) -> None:
        handler = self._make_handler(None)
        user_id = await handler._authenticate_ws_request(_FakeRequest(None))
        self.assertEqual(user_id, "anonymous")

    async def test_missing_token_is_rejected(self) -> None:
        handler = self._make_handler(AsyncMock())
        user_id = await handler._authenticate_ws_request(_FakeRequest(None))
        self.assertIsNone(user_id)

    async def test_valid_token_resolves_user_id(self) -> None:
        store = AsyncMock()
        store.get_user_id_for_token.return_value = "user-123"
        handler = self._make_handler(store)
        user_id = await handler._authenticate_ws_request(_FakeRequest("tok"))
        self.assertEqual(user_id, "user-123")
        store.get_user_id_for_token.assert_awaited_once_with("tok")

    async def test_invalid_token_is_rejected(self) -> None:
        store = AsyncMock()
        store.get_user_id_for_token.return_value = None
        handler = self._make_handler(store)
        user_id = await handler._authenticate_ws_request(_FakeRequest("bad"))
        self.assertIsNone(user_id)


if __name__ == "__main__":
    unittest.main()
