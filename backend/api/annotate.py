"""
后台预热注释模块
筛选完成后静默预热推荐条目的注释结果，用户点击"开始注释"时从缓存读取。
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from openai import AsyncOpenAI

from api.subtitles import _build_annotation_prompt, _call_ai_batch_async, _dynamic_batches, _inject_context
from models.schemas import AIAnnotateRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# 预热缓存: {cache_key: {"status": "done"|"failed", "data": {...}, "error": str}}
# cache_key = f"{task_id}:{purpose}:{index}"
_preheat_cache: dict[str, dict] = {}
_cache_lock = asyncio.Lock()


class PreheatRequest(AIAnnotateRequest):
    task_id: str


def get_cached_items(task_id: str, purpose: str) -> dict[int, dict]:
    """返回 task 下已完成的缓存条目 {index: data}，供 SSE 端点调用"""
    prefix = f"{task_id}:{purpose}:"
    result = {}
    for key, val in _preheat_cache.items():
        if key.startswith(prefix) and val["status"] == "done":
            try:
                index = int(key.rsplit(":", 1)[-1])
                result[index] = val["data"]
            except (ValueError, KeyError):
                pass
    return result


@router.post("/preheat")
async def preheat(request: PreheatRequest, background_tasks: BackgroundTasks):
    """筛选完成后调用，后台异步预热推荐条目的注释"""
    if not request.task_id:
        return {"status": "skipped", "reason": "no task_id"}

    subtask_key = f"{request.task_id}:{request.purpose}"

    async with _cache_lock:
        for sub in request.subtitles:
            cache_key = f"{subtask_key}:{sub.index}"
            if cache_key not in _preheat_cache:
                _preheat_cache[cache_key] = {"status": "pending", "data": None}

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]

    background_tasks.add_task(
        _run_preheat,
        request.task_id,
        request.purpose,
        subtitle_dicts,
        request.api_key or os.getenv("DEEPSEEK_API_KEY"),
        request.api_base or "https://api.deepseek.com",
        request.model_name or "deepseek-chat",
        request.source_language,
        request.target_language,
        request.custom_prompt,
    )

    return {"status": "preheating", "count": len(subtitle_dicts)}


@router.get("/preheat/{task_id}/status")
async def preheat_status(task_id: str):
    """查询预热进度"""
    done = 0
    failed = 0
    total = 0
    prefix = f"{task_id}:"
    for key, val in _preheat_cache.items():
        if key.startswith(prefix):
            total += 1
            if val["status"] == "done":
                done += 1
            elif val["status"] == "failed":
                failed += 1
    return {"done": done, "failed": failed, "total": total}


async def _run_preheat(
    task_id: str,
    purpose: str,
    subtitles: list,
    api_key: str,
    api_base: str,
    model_name: str,
    source_language: str,
    target_language: str,
    custom_prompt: str | None,
):
    """后台注释任务，结果写入 _preheat_cache"""
    if not api_key:
        logger.warning(f"预热跳过：无 API Key (task={task_id})")
        return

    system_prompt = _build_annotation_prompt(
        purpose, source_language, target_language, custom_prompt
    )

    enriched = _inject_context(subtitles)
    batches = _dynamic_batches(enriched, max_chars=1500)
    numbered_batches = [(i + 1, b) for i, b in enumerate(batches)]

    semaphore = asyncio.Semaphore(3)
    client = AsyncOpenAI(api_key=api_key, base_url=api_base)
    subtask_key = f"{task_id}:{purpose}"

    async def process_one(num: int, batch: list):
        items, error = await _call_ai_batch_async(
            client, system_prompt, batch, model_name, semaphore
        )
        if error:
            logger.warning(f"预热批次 {num} 失败: {error}")
            async with _cache_lock:
                for item in batch:
                    cache_key = f"{subtask_key}:{item['index']}"
                    if cache_key in _preheat_cache:
                        _preheat_cache[cache_key] = {"status": "failed", "data": None, "error": error}
            return

        async with _cache_lock:
            item_map = {item["index"]: item for item in (items or [])}
            for sub in batch:
                idx = sub["index"]
                result_item = item_map.get(idx)
                cache_key = f"{subtask_key}:{idx}"
                if result_item:
                    _preheat_cache[cache_key] = {"status": "done", "data": result_item}
                else:
                    _preheat_cache[cache_key] = {
                        "status": "done",
                        "data": {"index": idx, "translation": "", "notes": "", "word": "", "definition": ""},
                    }

    tasks = [asyncio.create_task(process_one(num, batch)) for num, batch in numbered_batches]
    await asyncio.gather(*tasks)
    logger.info(f"预热完成：task={task_id} purpose={purpose} 共 {len(subtitles)} 条")
