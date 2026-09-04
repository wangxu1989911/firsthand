"""The real provider client never hits a network in tests — httpx.MockTransport stands in.

It still must not be reachable by accident: the orchestrator suite injects
RecordedLLM. These tests only pin the request shape, the retry policy and the
error surface.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import BaseModel

from firsthand.config import Settings
from firsthand.llm import LLMError
from firsthand.llm.openai import OpenAILLM


class _Verdict(BaseModel):
    ok: bool


def _client(handler: object, **kwargs: object) -> OpenAILLM:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(base_url="https://llm.test/v1", transport=transport)
    params: dict[str, object] = {
        "api_key": "k",
        "base_url": "https://llm.test/v1",
        "chat_model": "m",
        "embedding_model": "e",
        "timeout_seconds": 5.0,
        "max_retries": 2,
        "client": http,
    }
    params.update(kwargs)
    return OpenAILLM(**params)  # type: ignore[arg-type]


async def test_structured_sends_redacted_prompt_and_parses_json_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    llm = _client(handler)
    got = await llm.structured(system="be brief", user="checkout is slow", schema=_Verdict)
    assert got == _Verdict(ok=True)
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert "checkout is slow" in str(seen["body"])
    assert "json_object" in str(seen["body"])


async def test_structured_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="try later")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": false}'}}]})

    got = await _client(handler).structured(system="s", user="u", schema=_Verdict)
    assert got.ok is False
    assert calls["n"] == 2


async def test_structured_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError, match="after 3 attempts"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)
    assert calls["n"] == 3


async def test_a_non_retryable_4xx_raises_immediately() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="no key")

    with pytest.raises(LLMError, match="401"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)


async def test_a_transport_error_is_retried_then_surfaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("reset")

    with pytest.raises(LLMError, match="after 3 attempts"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)


async def test_non_json_content_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    with pytest.raises(LLMError, match="did not return JSON"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)


async def test_unexpected_completion_shape_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": []})

    with pytest.raises(LLMError, match="unexpected chat-completions shape"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)


async def test_json_that_violates_the_schema_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": "banana"}'}}]})

    with pytest.raises(LLMError, match="did not match _Verdict"):
        await _client(handler).structured(system="s", user="u", schema=_Verdict)


async def test_embed_returns_vectors_sorted_by_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    assert await _client(handler).embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


async def test_embed_short_circuits_on_empty_input() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("should not call the API for zero inputs")

    assert await _client(handler).embed([]) == []


async def test_unexpected_embeddings_shape_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0}]})

    with pytest.raises(LLMError, match="unexpected embeddings shape"):
        await _client(handler).embed(["a"])


async def test_from_settings_builds_a_client_and_requires_a_key() -> None:
    settings = Settings(llm_api_key="live-key")
    llm = OpenAILLM.from_settings(settings)
    await llm.aclose()

    with pytest.raises(ValueError, match="api key is required"):
        OpenAILLM.from_settings(Settings(llm_api_key=""))


async def test_aclose_only_closes_a_client_it_owns() -> None:
    http = httpx.AsyncClient(base_url="https://llm.test/v1")
    llm = _client(lambda request: httpx.Response(200, json={}), client=http)
    await llm.aclose()
    assert not http.is_closed
    await http.aclose()


def _no_sleep(_seconds: float) -> object:
    async def _noop() -> None:
        return None

    return _noop()
