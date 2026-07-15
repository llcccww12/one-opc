"""Tests that LLMProvider.chat_stream retries a transient relay disconnect
(litellm.InternalServerError et al) when it happens before any content was
yielded, and does NOT retry once content has already streamed to the caller
(a retry there would re-issue the whole request and duplicate output)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import litellm

from opc.core.config import LLMConfig
from opc.llm.provider import LLMProvider


def _chunk(text: str | None = None, finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(
        content=text,
        reasoning=None,
        reasoning_content=None,
        thinking=None,
        tool_calls=[],
    )
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
    )


async def _fake_stream(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class ChatStreamDisconnectRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_disconnect_before_any_content(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="anthropic/mimo-v2.5-pro"))
        disconnect = litellm.InternalServerError(
            message="AnthropicException - Server disconnected",
            llm_provider="anthropic",
            model="mimo-v2.5-pro",
        )
        calls = {"n": 0}

        async def fake_acompletion(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise disconnect
            return _fake_stream([_chunk("hello", finish_reason="stop")])

        with patch("opc.llm.provider.litellm.acompletion", side_effect=fake_acompletion):
            events = [e async for e in provider.chat_stream([{"role": "user", "content": "hi"}])]

        self.assertEqual(calls["n"], 2)
        texts = [e.payload.get("text") for e in events if e.event_type == "assistant_delta"]
        self.assertEqual(texts, ["hello"])
        self.assertFalse(any(e.event_type == "error" for e in events))

    async def test_does_not_retry_after_content_already_streamed(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="anthropic/mimo-v2.5-pro"))
        disconnect = litellm.InternalServerError(
            message="AnthropicException - Server disconnected",
            llm_provider="anthropic",
            model="mimo-v2.5-pro",
        )

        async def fake_stream_then_disconnect():
            yield _chunk("partial")
            raise disconnect

        calls = {"n": 0}

        async def fake_acompletion(**kwargs):
            calls["n"] += 1
            return fake_stream_then_disconnect()

        with patch("opc.llm.provider.litellm.acompletion", side_effect=fake_acompletion):
            with self.assertRaises(litellm.InternalServerError):
                _ = [e async for e in provider.chat_stream([{"role": "user", "content": "hi"}])]

        self.assertEqual(calls["n"], 1)

    async def test_gives_up_after_max_attempts_still_disconnecting_before_content(self) -> None:
        provider = LLMProvider(LLMConfig(default_model="anthropic/mimo-v2.5-pro"))
        disconnect = litellm.InternalServerError(
            message="AnthropicException - Server disconnected",
            llm_provider="anthropic",
            model="mimo-v2.5-pro",
        )
        calls = {"n": 0}

        async def fake_acompletion(**kwargs):
            calls["n"] += 1
            raise disconnect

        with patch("opc.llm.provider.litellm.acompletion", side_effect=fake_acompletion):
            with patch("opc.llm.provider.asyncio.sleep", return_value=None):
                with self.assertRaises(litellm.InternalServerError):
                    _ = [e async for e in provider.chat_stream([{"role": "user", "content": "hi"}])]

        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main()
