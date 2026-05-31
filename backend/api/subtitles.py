"""字幕相关 API — 薄路由层，委托给 ai_batch / prompts / transcribe 模块"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI

# Ensure project root is importable (for core/, errors.py, models/)
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from models.schemas import (
    SubtitleItem, SubtitleListResponse, AIRecommendRequest,
    AIRecommendItem, AIRecommendResponse, AIAnnotateRequest,
    ASREngineInfo,
)
from core.parse_srt import parse_srt, filter_short_subtitles
from core.whisper_manager import is_whisper_installed, install_whisper
from errors import translate_error, ErrorCode, is_transient

logger = logging.getLogger(__name__)

# ── Local helpers (temp dir, ffmpeg detection) ──

_TEXT_SUBTITLE_CODECS = {"subrip", "mov_text", "webvtt", "ass", "ssa", "srt", "sami", "microdvd", "text", "eia_608", "eia_708"}


def _get_temp_dir() -> Path:
    """获取临时目录（兼容打包和开发环境）"""
    base = _get_base_dir()
    temp_dir = base / "temp"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir


def _get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
    return Path(__file__).parent.parent.parent


_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _get_bin_path(tool_name: str) -> str:
    if getattr(sys, 'frozen', False):
        possible_paths = [
            Path(sys._MEIPASS) / "bin" / tool_name,
            Path(sys.executable).parent / "bin" / tool_name,
            Path(sys.executable).parent / tool_name,
            Path(sys._MEIPASS) / tool_name,
        ]
        for p in possible_paths:
            if p.exists():
                return str(p)
        logger.warning(f"{tool_name} not found in any expected location")
    return tool_name


# ── Progress store (for legacy sync recommend endpoint polling) ──

_recommend_store: Dict[str, Any] = {}
_recommend_lock = threading.Lock()


# ── Router endpoints ──

router = APIRouter()


# ─────────────────── Upload & Extract ───────────────────


@router.post("/upload", response_model=SubtitleListResponse)
async def upload_subtitle(
    file: UploadFile = File(...),
    min_duration: float = 1.0,
):
    if not file.filename.endswith('.srt'):
        raise HTTPException(status_code=400, detail="只支持 .srt 格式的字幕文件")

    temp_dir = _get_temp_dir()
    temp_path = temp_dir / f"temp_{file.filename}"

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        subtitles = parse_srt(str(temp_path))
        original_count = len(subtitles)
        subtitles = filter_short_subtitles(subtitles, min_duration)
        subtitle_items = [SubtitleItem.from_subtitle(sub) for sub in subtitles]

        return SubtitleListResponse(
            subtitles=subtitle_items, total=original_count, filtered=len(subtitle_items)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析字幕失败: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/extract-embedded-subs")
async def extract_embedded_subtitles(
    video: UploadFile = File(...),
    stream_index: int = 0,
    min_duration: float = 1.0,
):
    if not video.filename:
        raise HTTPException(status_code=400, detail="未提供视频文件")

    temp_dir = _get_temp_dir()
    video_path = temp_dir / f"extract_{video.filename}"

    try:
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)

        # ffprobe to detect subtitle streams
        ffprobe_path = _get_bin_path("ffprobe.exe" if os.name == 'nt' else "ffprobe")
        probe_result = subprocess_run(
            [ffprobe_path, "-v", "error",
             "-select_streams", "s",
             "-show_entries", "stream=index,codec_name:stream_tags=language,title",
             "-of", "json", str(video_path)],
            timeout=30,
        )

        if probe_result.returncode != 0:
            logger.error(f"ffprobe failed: {probe_result.stderr}")
            raise HTTPException(status_code=500, detail=f"ffprobe 检测失败: {probe_result.stderr[:200]}")

        probe_data = json.loads(probe_result.stdout)
        streams = probe_data.get("streams", [])

        if not streams:
            return {"found": False, "streams": [], "extracted": None,
                    "message": "视频中没有内嵌字幕，请使用 Whisper 转录"}

        subtitle_streams = []
        for s in streams:
            codec = s.get("codec_name", "unknown")
            tags = s.get("tags", {})
            subtitle_streams.append({
                "index": s.get("index", 0), "codec": codec,
                "language": tags.get("language", "unknown"),
                "title": tags.get("title", ""),
                "text_based": codec in _TEXT_SUBTITLE_CODECS,
            })

        text_streams = [s for s in subtitle_streams if s["text_based"]]
        image_streams = [s for s in subtitle_streams if not s["text_based"]]

        if not text_streams:
            names = ", ".join(s["codec"] for s in image_streams)
            return {"found": True, "streams": subtitle_streams, "extracted": None,
                    "message": f"内嵌字幕为图像格式（{names}），无法直接提取文本，请使用 Whisper 转录"}

        if stream_index >= len(text_streams):
            stream_index = 0
        target = text_streams[stream_index]

        srt_path = temp_dir / f"extracted_{video.filename}.srt"
        ffmpeg_path = _get_bin_path("ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        subprocess_run([
            ffmpeg_path, "-y", "-i", str(video_path),
            "-map", f"0:s:{stream_index}", "-f", "srt", str(srt_path)
        ], timeout=60)

        if not srt_path.exists() or srt_path.stat().st_size == 0:
            return {"found": True, "streams": subtitle_streams, "extracted": None,
                    "message": "提取字幕失败，请尝试 Whisper 转录"}

        import_subs = parse_srt(str(srt_path))
        orig_count = len(import_subs)
        import_subs = filter_short_subtitles(import_subs, min_duration)
        items = [SubtitleItem.from_subtitle(s) for s in import_subs]

        return {
            "found": True, "streams": subtitle_streams,
            "extracted": {
                "stream_index": target["index"], "codec": target["codec"],
                "language": target["language"],
                "subtitles": [s.model_dump() for s in items],
                "total": orig_count, "filtered": len(items),
            },
            "message": f"已从视频提取 {len(items)} 条内嵌字幕",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提取字幕失败: {str(e)}")
    finally:
        if video_path.exists():
            video_path.unlink()
        srt_temp = temp_dir / f"extracted_{video.filename}.srt"
        if srt_temp.exists():
            srt_temp.unlink(missing_ok=True)


# ─────────────────── AI Recommend (legacy sync) ───────────────────


@router.post("/ai-recommend")
async def ai_recommend(request: AIRecommendRequest):
    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]

    task_id = str(uuid.uuid4())

    thread = threading.Thread(
        target=_sync_ai_recommend_loop,
        args=(task_id, subtitle_dicts, api_key, request.api_base, request.model_name,
              request.batch_size, request.ai_concurrency, request.source_language,
              request.target_language, request.purpose,
              request.correct_text, request.custom_prompt),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id, "status": "started"}


@router.get("/ai-recommend/progress/{task_id}")
async def ai_recommend_progress(task_id: str):
    with _recommend_lock:
        task = _recommend_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _sync_ai_recommend_loop(
    task_id: str,
    subtitle_dicts: list,
    api_key: str,
    api_base: str | None,
    model_name: str,
    batch_size: int,
    concurrency: int,
    source_lang: str,
    target_lang: str,
    purpose: str | None,
    correct_text: bool,
    custom_prompt: str | None,
) -> None:
    """Sync wrapper: calls async ai_batch.call_and_emit via asyncio.run() in-thread."""
    from openai import OpenAI

    max_bs = max(1, min(100, batch_size))
    batches_raw = _split_chunks(subtitle_dicts, max_bs)
    total_batches = len(batches_raw)

    def emit_progress(ev):
        if ev.phase == "starting":
            msg = "开始分析..."
        elif ev.phase == "complete":
            msg = f"分析完成，共 {ev.items_count} 条"
        else:
            msg = f"处理第 {ev.batch_num}/{total_batches} 批 ({batches_raw[ev.batch_num - 1][0].get('text', '')[:30]}...)..."
        with _recommend_lock:
            _recommend_store[task_id] = {
                "status": "processing",
                "batch": ev.batch_num,
                "total_batches": total_batches,
                "message": msg,
            }

    from .prompts import build_system_prompt
    client = OpenAI(api_key=api_key, base_url=api_base or "https://api.deepseek.com")
    system_prompt = build_system_prompt(custom_prompt, source_lang, target_lang)

    results = []
    for i, batch in enumerate(batches_raw):
        with _recommend_lock:
            _recommend_store[task_id]["batch"] = i + 1
        with _recommend_lock:
            _recommend_store[task_id]["message"] = f"处理第 {i+1}/{total_batches} 批..."

        # Synchronous call using sync OpenAI client
        try:

            items, error = _sync_call_single(client, system_prompt, batch, model_name)
            if items:
                results.extend(items)
            else:
                reason = f"处理失败: {error}" if error else "无结果"
                for item in batch:
                    results.append({"index": item["index"], "include": False, "reason": reason})

        except Exception as e:
            _, err_msg = translate_error(e)
            with _recommend_lock:
                _recommend_store[task_id] = {
                    "status": "error", "message": err_msg,
                    "error": err_msg, "error_code": ErrorCode.API_ERROR.value,
                }
            return

    # Build final result
    recommendations = []
    for item in results:
        recommendations.append(AIRecommendItem(
            index=item.get("index", 0), include=item.get("include", False),
            reason=item.get("reason", ""),
            translation=item.get("translation") if item.get("include") else None,
            notes=item.get("notes") if item.get("include") else None,
            word=item.get("word") if item.get("include") else None,
            definition=item.get("definition") if item.get("include") else None,
        ))

    with _recommend_lock:
        _recommend_store[task_id] = {
            "status": "completed",
            "batch": total_batches,
            "message": f"分析完成，共 {len(recommendations)} 条",
            "result": AIRecommendResponse(recommendations=recommendations).model_dump(),
        }


def _sync_call_single(client, system_prompt: str, batch: list, model_name: str) -> tuple[list, str]:
    """Synchronous single-batch AI call (same logic as _call_ai_batch_async but sync)."""
    import time as _time
    for attempt in range(3 + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                items = parsed.get("items") or parsed.get("results") or []
            elif isinstance(parsed, list):
                items = parsed
            else:
                items = []
            return items, ""
        except Exception as e:
            last_error = translate_error(e)[1]
            if is_transient(e) and attempt < 3:
                delay = [2, 5, 10][attempt]
                _time.sleep(delay)
            else:
                return [], last_error
    return [], last_error


def _split_chunks(lst: list, n: int) -> list[list]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


# ─────────────────── AI Streaming Endpoints ───────────────────


@router.post("/ai-recommend-stream")
async def ai_recommend_stream(request: AIRecommendRequest):
    from .ai_batch import stream_batches, BatchPostProcess, ProgressEvent

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]
    semaphore = asyncio.Semaphore(request.ai_concurrency)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=request.api_base or "https://api.deepseek.com")
        yield f"data: {json.dumps({'type': 'start', 'total_batches': 0})}\n\n"

        num_batches_seen = 0
        async for num, items, error in stream_batches(
            client, phase="screening", batches_raw=subtitle_dicts,
            custom_prompt=request.custom_prompt, correct_text=request.correct_text,
            source_language=request.source_language, target_language=request.target_language,
            model_name=request.model_name or "deepseek-chat",
            semaphore=semaphore,
        ):
            if num == 0:
                continue  # skip sentinel
            num_batches_seen += 1
            yield f"data: {json.dumps({'type': 'batch', 'batch': num_batches_seen, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/ai-screen-stream")
async def ai_screen_stream(request: AIRecommendRequest):
    from .ai_batch import stream_batches, BatchPostProcess

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]
    semaphore = asyncio.Semaphore(request.ai_concurrency)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=request.api_base or "https://api.deepseek.com")
        yield f"data: {json.dumps({'type': 'start', 'total_batches': 0})}\n\n"

        num_batches_seen = 0
        async for num, items, error in stream_batches(
            client, phase="screening", batches_raw=subtitle_dicts,
            custom_prompt=request.custom_prompt, correct_text=request.correct_text,
            enrich_context=False,
            source_language=request.source_language, target_language=request.target_language,
            model_name=request.model_name or "deepseek-chat",
            semaphore=semaphore,
            post_process=BatchPostProcess(strip_annotation_fields=True, include_corrected=request.correct_text),
        ):
            if num == 0:
                continue  # skip sentinel
            num_batches_seen += 1
            yield f"data: {json.dumps({'type': 'batch', 'batch': num_batches_seen, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/ai-annotate-stream")
async def ai_annotate_stream(request: AIAnnotateRequest):
    from .ai_batch import stream_batches, BatchPostProcess

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]

    cached_lookup = None
    if request.task_id:
        try:
            from api.annotate import get_cached_items
            cached_lookup = get_cached_items(request.task_id, request.purpose)
        except ImportError:
            pass

    semaphore = asyncio.Semaphore(request.ai_concurrency)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=request.api_base or "https://api.deepseek.com")
        yield f"data: {json.dumps({'type': 'start', 'total_batches': 0})}\n\n"

        num_batches_seen = 0
        async for num, items, error in stream_batches(
            client, phase="annotation", purpose=request.purpose,
            batches_raw=subtitle_dicts, enrich_context=True,
            custom_prompt=request.custom_prompt,
            source_language=request.source_language, target_language=request.target_language,
            model_name=request.model_name or "deepseek-chat",
            semaphore=semaphore,
            post_process=BatchPostProcess(cache_lookup=cached_lookup),
        ):
            if num == 0:
                continue  # skip sentinel
            num_batches_seen += 1
            yield f"data: {json.dumps({'type': 'batch', 'batch': num_batches_seen, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─────────────────── Transcription ───────────────────


_transcribe_store: Dict[str, Any] = {}
_transcribe_lock = threading.Lock()


@router.post("/transcribe")
async def transcribe_video_endpoint(
    video: UploadFile = File(...),
    min_duration: float = 1.0,
    language: Optional[str] = None,
    model_name: str = "base",
    asr_engine: str = "faster_whisper",
):
    if asr_engine == "faster_whisper" and not is_whisper_installed():
        raise HTTPException(status_code=400, detail="Whisper 未安装，请先调用 POST /api/subtitles/whisper/install 安装")
    elif asr_engine not in ("faster_whisper", "bcut"):
        raise HTTPException(status_code=400, detail=f"未知的 ASR 引擎: {asr_engine}")

    if not video.filename:
        raise HTTPException(status_code=400, detail="未提供视频文件")

    temp_dir = _get_temp_dir()
    video_path = temp_dir / f"transcribe_{video.filename}"
    srt_path = temp_dir / f"transcribe_{video.filename}.srt"

    with open(video_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    task_id = str(uuid.uuid4())

    with _transcribe_lock:
        _transcribe_store[task_id] = {
            "status": "preparing", "step": 0, "total_steps": 4, "message": "准备转录...",
        }

    # Import here to avoid startup-time heavy imports
    from .transcribe import run_transcribe

    thread = threading.Thread(
        target=run_transcribe,
        args=(task_id, str(video_path), str(srt_path), asr_engine, model_name,
              language, min_duration, _transcribe_store, _transcribe_lock),
        daemon=True,
    )
    thread.start()

    return {"task_id": task_id, "status": "started"}


@router.get("/transcribe/progress/{task_id}")
async def transcribe_progress(task_id: str):
    with _transcribe_lock:
        task = _transcribe_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {k: v for k, v in task.items() if not k.startswith("_")}


@router.post("/transcribe/cancel/{task_id}")
async def cancel_transcribe(task_id: str):
    with _transcribe_lock:
        task = _transcribe_store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        task["_cancelled"] = True
        proc = task.get("_proc")
    if proc is not None and proc.is_alive():
        proc.terminate()
    return {"status": "cancelling", "message": "转录取消中..."}


# ─────────────────── Health & Status ───────────────────


def subprocess_run(cmd: list, timeout: int = 30):
    """Run subprocess with platform-safe flags."""
    return subprocess.run(cmd, capture_output=True, encoding='utf-8', errors='replace',
                          timeout=timeout, **_NO_WINDOW)


def _check_ffmpeg_installed() -> dict:
    ffmpeg_path = _get_bin_path("ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
    try:
        result = subprocess_run([ffmpeg_path, "-version"], timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0] if result.stdout else ""
            return {"installed": True, "version": version_line, "path": ffmpeg_path}
        return {"installed": False, "version": None, "path": ffmpeg_path,
                "reason": "ffmpeg 执行返回非零退出码"}
    except FileNotFoundError:
        return {"installed": False, "version": None, "path": ffmpeg_path,
                "reason": "未找到 ffmpeg 可执行文件"}
    except subprocess.TimeoutExpired:
        return {"installed": False, "version": None, "path": ffmpeg_path,
                "reason": "ffmpeg 响应超时"}
    except Exception as e:
        return {"installed": False, "version": None, "path": ffmpeg_path,
                "reason": str(e)[:200]}


@router.get("/ffmpeg/status")
async def ffmpeg_status():
    return _check_ffmpeg_installed()


@router.get("/whisper/status")
async def whisper_status():
    installed = is_whisper_installed()
    mode = "dev" if not getattr(sys, 'frozen', False) else "frozen"
    return {"installed": installed, "mode": mode}


@router.post("/whisper/install")
async def whisper_install():
    if is_whisper_installed():
        return {"status": "already_installed", "message": "Whisper 已安装"}
    success, error = install_whisper()
    if success:
        return {"status": "success", "message": "Whisper 安装成功"}
    raise HTTPException(status_code=500, detail=f"Whisper 安装失败: {error}")


@router.get("/asr/engines")
async def get_asr_engines():
    import core.asr.whisper_engine  # noqa: F401
    import core.asr.bcut_engine     # noqa: F401
    from core.asr import get_available_engines
    engines = get_available_engines()
    return {"engines": [ASREngineInfo(**e).model_dump() for e in engines]}


@router.get("/example", response_model=SubtitleListResponse)
async def get_example_subtitles():
    example_data = [
        SubtitleItem(index=1, start_sec=83.456, end_sec=85.789, text="Hello, how are you?", duration=2.333),
        SubtitleItem(index=2, start_sec=86.123, end_sec=89.456, text="I'm doing great, thanks for asking!", duration=3.333),
        SubtitleItem(index=3, start_sec=90.123, end_sec=94.567, text="What have you been up to lately?", duration=4.444),
    ]
    return SubtitleListResponse(subtitles=example_data, total=3, filtered=3)


@router.get("/learned-words")
async def get_learned_words():
    from services.progress import get_learned_words, get_learned_count
    words = get_learned_words()
    return {"words": words, "count": len(words)}


@router.post("/sync-learned-from-anki")
async def sync_learned_from_anki(body: dict):
    from services.progress import mark_words_learned, get_learned_count
    words = body.get("words", [])
    if not words:
        return {"synced": 0, "total": get_learned_count()}
    word_dicts = [{"word": w, "definition": ""} for w in words if isinstance(w, str) and w.strip()]
    mark_words_learned(word_dicts, source_video="anki-sync")
    return {"synced": len(word_dicts), "total": get_learned_count()}


# ── Backward-compat re-exports (for annotate.py imports) ──

from .prompts import build_annotation_prompt as _build_annotation_prompt
from .ai_batch import call_ai_batch_async as _call_ai_batch_async, dynamic_batches as _dynamic_batches, inject_context as _inject_context
