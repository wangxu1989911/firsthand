"""RecordedLLM is the only client tests use — an un-recorded call must be loud."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from firsthand.llm import FixtureMissError, LLMError, RecordedLLM
from firsthand.llm.fixtures import embedding_key, structured_key


class _Reply(BaseModel):
    verdict: str
    score: int


async def test_structured_replays_a_recorded_completion() -> None:
    key = structured_key("_Reply", "sys", "user text")
    llm = RecordedLLM(completions={key: {"verdict": "ok", "score": 3}})
    got = await llm.structured(system="sys", user="user text", schema=_Reply)
    assert got == _Reply(verdict="ok", score=3)
    assert llm.structured_calls == [("_Reply", "sys", "user text")]


async def test_a_missing_completion_raises_fixture_miss() -> None:
    with pytest.raises(FixtureMissError, match="no recorded _Reply completion"):
        await RecordedLLM().structured(system="s", user="u", schema=_Reply)


async def test_a_recorded_blob_that_no_longer_validates_raises_llm_error() -> None:
    key = structured_key("_Reply", "s", "u")
    llm = RecordedLLM(completions={key: {"verdict": "ok"}})  # missing "score"
    with pytest.raises(LLMError, match="no longer validates"):
        await llm.structured(system="s", user="u", schema=_Reply)


async def test_embed_replays_vectors_in_input_order() -> None:
    llm = RecordedLLM(embeddings={embedding_key("a"): [1.0, 0.0], embedding_key("b"): [0.0, 1.0]})
    assert await llm.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert llm.embed_calls == [["a", "b"]]


async def test_a_missing_embedding_raises_fixture_miss() -> None:
    with pytest.raises(FixtureMissError, match="no recorded embedding"):
        await RecordedLLM().embed(["x"])


async def test_from_file_loads_completions_and_embeddings(tmp_path: Path) -> None:
    key = structured_key("_Reply", "s", "u")
    blob = {
        "completions": {key: {"verdict": "ok", "score": 1}},
        "embeddings": {embedding_key("hi"): [0.5, 0.5]},
    }
    path = tmp_path / "fx.json"
    path.write_text(json.dumps(blob), encoding="utf-8")

    llm = RecordedLLM.from_file(path)
    assert (await llm.structured(system="s", user="u", schema=_Reply)).score == 1
    assert await llm.embed(["hi"]) == [[0.5, 0.5]]


def test_keys_change_with_every_input_component() -> None:
    base = structured_key("A", "sys", "user")
    assert structured_key("B", "sys", "user") != base
    assert structured_key("A", "SYS", "user") != base
    assert structured_key("A", "sys", "USER") != base
    assert embedding_key("a") != embedding_key("b")
