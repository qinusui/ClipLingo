"""AI 批次调用统一入口 — prompt 构建、分批、并发调用、事件 emit"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from errors import is_transient

logger = logging.getLogger(__name__)

# ── Typed event interface ──


@dataclass(frozen=True)
class ProgressEvent:
    phase: Literal["starting", "batch_done", "batch_failed", "complete", "error"]
    batch_num: int
    total_batches: int
    items_count: int
    error: str = ""


@dataclass
class BatchPostProcess:
    """端点特定的 post-processing hook"""
    strip_annotation_fields: bool = False
    include_corrected: bool = False
    cache_lookup: dict[int, dict] | None = None


# ── Internal helpers (implementation, not exported) ──

_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]

_PROMPT_PHASES = {
    "screening": "screening",
    "annotation": "annotation",
}


def _parse_ai_items(parsed: dict | list) -> list[dict]:
    """从 AI 返回的 JSON 中提取 items 列表"""
    if isinstance(parsed, dict):
        items = parsed.get("items") or parsed.get("results")
        if items and isinstance(items, list):
            return items
        for v in parsed.values():
            if isinstance(v, list):
                return v
    elif isinstance(parsed, list):
        return parsed
    return []


def _dynamic_batches(subtitle_dicts: list, max_chars: int = 3000) -> list[list]:
    """按字符数动态分批，避免长短不一导致的负载不均"""
    batches: list[list] = []
    current_batch: list = []
    current_chars = 0

    for item in subtitle_dicts:
        item_chars = len(item.get("text", ""))
        if item_chars > max_chars:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            batches.append([item])
            continue
        if current_batch and current_chars + item_chars > max_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += item_chars

    if current_batch:
        batches.append(current_batch)

    return batches


def _inject_context(subtitle_dicts: list) -> list:
    """为每条字幕注入前后各一句的文本作为翻译上下文"""
    result: list[dict] = []
    for i, item in enumerate(subtitle_dicts):
        enriched = dict(item)
        if i > 0:
            enriched["prev_text"] = subtitle_dicts[i - 1].get("text", "")
        if i < len(subtitle_dicts) - 1:
            enriched["next_text"] = subtitle_dicts[i + 1].get("text", "")
        result.append(enriched)
    return result


def _apply_postprocess(items: list[dict], pp: BatchPostProcess) -> list[dict]:
    """端点特定的后处理：剥离字段 / 合并缓存"""
    if not items or not pp.strip_annotation_fields:
        # screen-stream 有 cache lookup（如果 annotate-stream 传了）
        pass

    if pp.cache_lookup and items:
        for i, item in enumerate(items):
            idx = item.get("index")
            if idx in pp.cache_lookup:
                items[i] = pp.cache_lookup[idx]

    if pp.strip_annotation_fields:
        for item in items:
            item.pop("translation", None)
            item.pop("notes", None)
            item.pop("word", None)
            item.pop("definition", None)
            if not pp.include_corrected:
                item.pop("corrected_text", None)

    return items


# ── Public async implementation ──


async def _call_single_batch(
    client,
    system_prompt: str,
    batch: list,
    model_name: str = "deepseek-chat",
    semaphore: asyncio.Semaphore | None = None,
) -> tuple[list[dict], str]:
    """异步调用一次 AI API（含指数退避抖动重试）"""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            if semaphore is not None:
                async with semaphore:
                    response = await client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2,
                        timeout=90.0,
                    )
            else:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    timeout=90.0,
                )

            content = response.choices[0].message.content
            parsed = json.loads(content)
            items = _parse_ai_items(parsed)

            # Ensure index/keys for downstream processing
            for i, item in enumerate(items):
                if "index" not in item:
                    item["index"] = batch[i]["index"] if i < len(batch) else 0
                if "include" not in item:
                    item["include"] = False
                if "reason" not in item:
                    item["reason"] = ""

            return items, ""

        except Exception as e:
            err_msg = str(e) or type(e).__name__
            last_error = f"AI call failed: {err_msg}"
            if is_transient(e) and attempt < _MAX_RETRIES:
                delay = min(2 ** attempt + random.random(), 30)
                logger.debug(f"Batch retry {attempt+1}/{_MAX_RETRIES}: {last_error}")
                await asyncio.sleep(delay)
            else:
                return [], last_error

    return [], last_error


async def call_and_emit(
    client,
    *,
    phase: Literal["screening", "annotation"],
    model_name: str = "deepseek-chat",
    purpose: str | None = None,
    custom_prompt: str | None = None,
    correct_text: bool = False,
    enrich_context: bool = False,
    source_language: str = "en",
    target_language: str = "zh",
    batches_raw: list[dict] | None = None,
    batches_prebatched: list[list[dict]] | None = None,
    semaphore: asyncio.Semaphore | None = None,
    post_process: BatchPostProcess | None = None,
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> list[dict]:
    """
    Collects all results and returns at end. For batch-oriented callers
    that don't need per-batch visibility (e.g. the legacy recommend endpoint).
    """
    from .prompts import build_screening_prompt, build_annotation_prompt

    # Build system prompt
    if phase == "screening":
        system_prompt = build_screening_prompt(custom_prompt, source_language, target_language, correct_text)
    else:
        system_prompt = build_annotation_prompt(purpose or "grammar", source_language, target_language, custom_prompt)

    # Prepare final batches
    if batches_prebatched is not None:
        final_batches = batches_prebatched
    else:
        assert batches_raw is not None
        working = batches_raw
        if enrich_context:
            working = _inject_context(working)
        final_batches = _dynamic_batches(working, max_chars=1500)

    total = len(final_batches)
    if on_progress:
        on_progress(ProgressEvent("starting", 0, total, 0))

    all_results: list[dict] = []

    async def run_one(num: int, batch: list[dict]) -> tuple[int, list[dict], str]:
        items, error = await _call_single_batch(client, system_prompt, batch, model_name, semaphore)
        return num, items, error

    tasks = [asyncio.create_task(run_one(i + 1, b)) for i, b in enumerate(final_batches)]

    for coro in asyncio.as_completed(tasks):
        num, items, error = await coro

        if not items and error:
            failed_batch = final_batches[num - 1]
            items = [{"index": it["index"], "include": False, "reason": f"处理失败: {error}"} for it in failed_batch]

        if post_process:
            items = _apply_postprocess(items, post_process)

        all_results.extend(items)

        event_phase = "batch_failed" if (not items or any(i.get("include") is False for i in items)) and error else "batch_done"
        if on_progress:
            on_progress(ProgressEvent(event_phase, num, total, len(items), error or ""))

    if on_progress:
        on_progress(ProgressEvent("complete", total, total, len(all_results)))

    return all_results


async def stream_batches(
    client,
    *,
    phase: Literal["screening", "annotation"],
    model_name: str = "deepseek-chat",
    purpose: str | None = None,
    custom_prompt: str | None = None,
    correct_text: bool = False,
    enrich_context: bool = False,
    source_language: str = "en",
    target_language: str = "zh",
    batches_raw: list[dict] | None = None,
    batches_prebatched: list[list[dict]] | None = None,
    semaphore: asyncio.Semaphore | None = None,
    post_process: BatchPostProcess | None = None,
) -> None:
    """
    Async generator-style: yields (num, items, error) tuples as each batch completes.
    SSE endpoints consume this to emit batch-by-batch events.
    """
    from .prompts import build_screening_prompt, build_annotation_prompt

    if phase == "screening":
        system_prompt = build_screening_prompt(custom_prompt, source_language, target_language, correct_text)
    else:
        system_prompt = build_annotation_prompt(purpose or "grammar", source_language, target_language, custom_prompt)

    if batches_prebatched is not None:
        final_batches = batches_prebatched
    else:
        assert batches_raw is not None
        working = batches_raw
        if enrich_context:
            working = _inject_context(working)
        final_batches = _dynamic_batches(working, max_chars=1500)

    total = len(final_batches)

    async def run_one(num: int, batch: list[dict]) -> tuple[int, list[dict], str]:
        # 缓存预检查：如果整个批次都命中缓存，跳过 AI 调用
        if post_process and post_process.cache_lookup:
            cached_items = []
            all_cached = True
            for item in batch:
                idx = item.get("index")
                if idx in post_process.cache_lookup:
                    cached_items.append(post_process.cache_lookup[idx])
                else:
                    all_cached = False
                    break
            if all_cached:
                return num, cached_items, ""

        items, error = await _call_single_batch(client, system_prompt, batch, model_name, semaphore)
        return num, items, error

    tasks = [asyncio.create_task(run_one(i + 1, b)) for i, b in enumerate(final_batches)]

    for coro in asyncio.as_completed(tasks):
        num, items, error = await coro

        if not items and error:
            failed_batch = final_batches[num - 1]
            items = [{"index": it["index"], "include": False, "reason": f"处理失败: {error}"} for it in failed_batch]

        if post_process:
            items = _apply_postprocess(items, post_process)

        yield num, items, error

    yield 0, [], ""  # sentinel: done


# ── Backward compat aliases (for annotate.py which imports these directly) ──

call_ai_batch_async = _call_single_batch
dynamic_batches = _dynamic_batches
inject_context = _inject_context
