"""Tests for ai_batch module — verifying call_and_emit and stream_batches."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from api.ai_batch import (
    ProgressEvent, BatchPostProcess, call_and_emit, stream_batches,
)


# ─── Mock factory: creates AsyncOpenAI-like client ───

def _make_async_mock_client(response_factory):
    """
    Create a mock client like AsyncOpenAI where chat.completions.create() is async.
    response_factory: callable -> list[dict], called per API invocation to produce items list.
    Returns (client, call_counter_list).
    """
    counter = [0]

    class Completions:
        @staticmethod
        async def create(*args, **kwargs):
            items = response_factory()
            body = {"items": items}
            choice = type("Choice", (), {
                "message": type("Message", (), {"content": json.dumps(body)})()
            })()
            return type("Response", (), {"choices": [choice]})()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client(), counter


# ─── Test 1: call_and_emit returns screening results ───


@pytest.mark.asyncio
async def test_call_and_emit_returns_screening_results():
    """call_and_emit builds a screening prompt, calls API, parses JSON, returns items list."""
    items_out = [
        {"index": 1, "include": True, "reason": "Useful sentence"},
        {"index": 2, "include": False, "reason": "Too simple"},
    ]
    client, _ = _make_async_mock_client(lambda: items_out)

    results = await call_and_emit(
        client,
        phase="screening",
        batches_raw=[{"index": 1, "text": "Hello world"}],
    )

    assert len(results) == 2
    assert results[0]["index"] == 1
    assert results[0]["include"] is True
    assert results[1]["index"] == 2
    assert results[1]["include"] is False


# ─── Test 2: ProgressEvent emitted via on_progress callback ───


@pytest.mark.asyncio
async def test_call_and_emit_emits_progress_events():
    """call_and_emit fires ProgressEvent per batch and at completion via on_progress."""
    events = []

    def record(ev):
        events.append(ev)

    client, _ = _make_async_mock_client(lambda: [{"index": 1, "include": True}])

    results = await call_and_emit(
        client,
        phase="annotation", purpose="grammar",
        batches_raw=[{"index": 1, "text": "Hello"}],
        on_progress=record,
    )

    phases = [e.phase for e in events]
    assert "starting" in phases
    assert "complete" in phases
    complete_ev = [e for e in events if e.phase == "complete"][0]
    assert complete_ev.items_count == 1


# ─── Test 3: Multiple input items → merged from single batch ───


@pytest.mark.asyncio
async def test_call_and_emit_merges_results_from_api():
    """Items returned by AI are passed through verbatim into results."""
    # 5 subtitles, small texts → 1 batch, AI returns 5 items
    client, _ = _make_async_mock_client(
        lambda: [{"index": i, "include": True} for i in range(1, 6)]
    )

    results = await call_and_emit(
        client,
        phase="screening",
        batches_raw=[{"index": i, "text": f"text {i}"} for i in range(1, 6)],
    )

    assert len(results) == 5
    indices = sorted(r["index"] for r in results)
    assert indices == [1, 2, 3, 4, 5]


# ─── Test 4: Post-process strips annotation fields ───


@pytest.mark.asyncio
async def test_post_process_strips_fields():
    """BatchPostProcess(strip_annotation_fields=True) removes translation/notes/word/definition."""
    client, _ = _make_async_mock_client(
        lambda: [{
            "index": 1, "include": True,
            "translation": "Hi", "notes": "greeting",
            "word": "hi", "definition": "expression of greeting",
        }]
    )

    pp = BatchPostProcess(strip_annotation_fields=True)
    results = await call_and_emit(
        client,
        phase="screening",
        batches_raw=[{"index": 1, "text": "Hi"}],
        post_process=pp,
    )

    assert "translation" not in results[0]
    assert "notes" not in results[0]
    assert "word" not in results[0]
    assert "definition" not in results[0]
    assert results[0]["index"] == 1


# ─── Test 5: stream_batches yields batch by batch ───


@pytest.mark.asyncio
async def test_stream_batches_yields_sequentially():
    """stream_batches yields (num, items, error) per completed batch, then sentinel."""
    client, _ = _make_async_mock_client(lambda: [{"index": 1, "include": True}])

    chunks = []
    async for num, items, error in stream_batches(
        client, phase="screening",
        batches_raw=[{"index": 1, "text": "Hello"}],
    ):
        chunks.append((num, len(items), error))

    # Last entry is done sentinel (error="", num=0)
    assert len(chunks) >= 2
    assert chunks[-1][0] == 0
    assert chunks[-1][2] == ""
    assert chunks[-1][1] == 0


# ─── Test 6: Cache merge in annotate mode ───


@pytest.mark.asyncio
async def test_stream_batches_merges_cache_preheat():
    """stream_batches with cache_lookup replaces AI results with cached values."""
    client, _ = _make_async_mock_client(
        lambda: [{"index": 1, "include": True, "translation": "FROM_AI"}]
    )

    cache = {1: {"index": 1, "include": True, "translation": "FROM_CACHE"}}
    pp = BatchPostProcess(cache_lookup=cache)

    chunks = []
    async for num, items, error in stream_batches(
        client, phase="annotation", purpose="grammar",
        batches_raw=[{"index": 1, "text": "Hello"}],
        enrich_context=True,
        post_process=pp,
    ):
        if num != 0:
            chunks.extend(items)

    assert len(chunks) == 1
    assert chunks[0]["translation"] == "FROM_CACHE"


# ─── Test 7: Failed batch emits skip entries ───


@pytest.mark.asyncio
async def test_stream_batches_emits_skip_on_api_failure():
    """When API raises exception, retries exhaust → yield skip entries so SSE timeline stays continuous."""
    attempts = [0]

    async def failing_create(*args, **kwargs):
        attempts[0] += 1
        # _MAX_RETRIES=3 → 4 total calls. All raise → retries exhaust → skip entries yielded.
        raise ConnectionError("API unreachable")

    completions = type("Completions", (), {"create": failing_create})()
    chat = type("Chat", (), {"completions": completions})()
    client = type("FailingClient", (), {"chat": chat})()

    chunks = []
    async for num, items, error in stream_batches(
        client, phase="screening",
        batches_raw=[{"index": 1, "text": "Hello"}, {"index": 2, "text": "World"}],
    ):
        if num != 0:
            chunks.append((num, len(items), error))

    # Both subtitles fit in one batch; retries exhaust → skip entries yielded
    assert len(chunks) == 1
    assert chunks[0][0] == 1         # batch number
    assert chunks[0][1] == 2         # 2 skip entries (one per original item)
    assert "API unreachable" in chunks[0][2]  # error message preserved


# ─── Test 8: Correction phase returns corrected_text ───


@pytest.mark.asyncio
async def test_call_and_emit_correction_phase():
    """call_and_emit with phase='correction' returns items with corrected_text."""
    items_out = [
        {"index": 1, "corrected_text": "Hello world"},
        {"index": 2, "corrected_text": "Good morning"},
    ]
    client, _ = _make_async_mock_client(lambda: items_out)

    results = await call_and_emit(
        client,
        phase="correction",
        batches_raw=[
            {"index": 1, "text": "Helo world"},
            {"index": 2, "text": "Good mornng"},
        ],
    )

    assert len(results) == 2
    assert results[0]["corrected_text"] == "Hello world"
    assert results[1]["corrected_text"] == "Good morning"


# ─── Test 9: stream_batches correction phase ───


@pytest.mark.asyncio
async def test_stream_batches_correction_phase():
    """stream_batches with phase='correction' yields corrected items."""
    client, _ = _make_async_mock_client(
        lambda: [{"index": 1, "corrected_text": "Fixed text"}]
    )

    chunks = []
    async for num, items, error in stream_batches(
        client, phase="correction",
        batches_raw=[{"index": 1, "text": "Brken text"}],
    ):
        if num != 0:
            chunks.extend(items)

    assert len(chunks) == 1
    assert chunks[0]["corrected_text"] == "Fixed text"
