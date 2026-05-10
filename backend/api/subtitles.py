"""
字幕相关 API
"""

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pathlib import Path
import tempfile
import shutil
import json
import os
import sys
import subprocess
import asyncio

# Windows 下防止子进程弹出终端窗口
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
import logging
from typing import List, Optional

from models.schemas import (
    SubtitleItem, SubtitleListResponse, AIRecommendRequest,
    AIRecommendItem, AIRecommendResponse, AIAnnotateRequest,
    EmbeddedSubtitleStream, ExtractEmbeddedResponse
)

# 导入现有的字幕解析模块
sys.path.append(str(Path(__file__).parent.parent.parent))
from core.parse_srt import parse_srt, filter_short_subtitles
from core.whisper_manager import is_whisper_installed, install_whisper
from errors import translate_error, is_transient, get_message, ErrorCode

logger = logging.getLogger(__name__)


def _get_base_dir() -> Path:
    """获取基础目录，兼容打包和开发环境"""
    if getattr(sys, 'frozen', False):
        # 打包后使用 %APPDATA% 避免 Program Files 权限问题
        return Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
    return Path(__file__).parent.parent.parent


def _get_bin_path(tool_name: str) -> str:
    """获取 ffmpeg/ffprobe 的路径，兼容打包和开发环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的路径查找
        possible_paths = [
            Path(sys._MEIPASS) / "bin" / tool_name,  # _internal/bin/
            Path(sys.executable).parent / "bin" / tool_name,  # exe 同级 bin/
            Path(sys.executable).parent / tool_name,  # exe 同级
            Path(sys._MEIPASS) / tool_name,  # _internal/
        ]
        for path in possible_paths:
            if path.exists():
                logger.info(f"Found {tool_name} at: {path}")
                return str(path)
        logger.warning(f"{tool_name} not found in any expected location")
    # 开发环境或 Docker - 直接使用命令名
    return tool_name


def _get_temp_dir() -> Path:
    """获取临时目录"""
    temp_dir = _get_base_dir() / "temp"
    temp_dir.mkdir(exist_ok=True)
    return temp_dir

router = APIRouter()


@router.post("/upload", response_model=SubtitleListResponse)
async def upload_subtitle(
    file: UploadFile = File(...),
    min_duration: float = 1.0
):
    """
    上传并解析字幕文件

    Args:
        file: SRT 字幕文件
        min_duration: 最短字幕时长（秒），过滤掉过短的对话

    Returns:
        SubtitleListResponse: 解析后的字幕列表
    """
    if not file.filename.endswith('.srt'):
        raise HTTPException(status_code=400, detail="只支持 .srt 格式的字幕文件")

    # 保存临时文件
    temp_dir = _get_temp_dir()
    temp_path = temp_dir / f"temp_{file.filename}"

    try:
        # 保存上传的文件
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 解析字幕
        subtitles = parse_srt(str(temp_path))

        # 过滤过短字幕
        original_count = len(subtitles)
        subtitles = filter_short_subtitles(subtitles, min_duration)

        # 转换为响应格式
        subtitle_items = [SubtitleItem.from_subtitle(sub) for sub in subtitles]

        return SubtitleListResponse(
            subtitles=subtitle_items,
            total=original_count,
            filtered=len(subtitle_items)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析字幕失败: {str(e)}")

    finally:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink()


# 可从视频提取的文本字幕编码
_TEXT_SUBTITLE_CODECS = {"subrip", "mov_text", "webvtt", "ass", "ssa", "srt", "sami", "microdvd", "text", "stl", "eia_608", "eia_708"}


@router.post("/extract-embedded-subs")
async def extract_embedded_subtitles(
    video: UploadFile = File(...),
    stream_index: int = 0,
    min_duration: float = 1.0
):
    """
    检测并提取视频内嵌字幕（优先于 Whisper 转录）

    Args:
        video: 视频文件
        stream_index: 要提取的字幕流序号（默认第一个）
        min_duration: 最短字幕时长

    Returns:
        ExtractEmbeddedResponse: 字幕流列表及提取结果
    """
    import subprocess

    if not video.filename:
        raise HTTPException(status_code=400, detail="未提供视频文件")

    temp_dir = _get_temp_dir()
    video_path = temp_dir / f"extract_{video.filename}"

    try:
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video.file, f)

        # 1. 用 ffprobe 检测字幕流
        ffprobe_path = _get_bin_path("ffprobe.exe" if os.name == 'nt' else "ffprobe")
        logger.info(f"Using ffprobe: {ffprobe_path}")
        probe_result = subprocess.run([
            ffprobe_path, "-v", "error",
            "-select_streams", "s",
            "-show_entries", "stream=index,codec_name:stream_tags=language,title",
            "-of", "json",
            str(video_path)
        ], capture_output=True, encoding='utf-8', errors='replace', timeout=30, **_NO_WINDOW)

        if probe_result.returncode != 0:
            logger.error(f"ffprobe failed: {probe_result.stderr}")
            raise HTTPException(status_code=500, detail=f"ffprobe 检测失败: {probe_result.stderr[:200]}")

        probe_data = json.loads(probe_result.stdout)
        streams = probe_data.get("streams", [])

        if not streams:
            return {"found": False, "streams": [], "extracted": None,
                    "message": "视频中没有内嵌字幕，请使用 Whisper 转录"}

        # 分类字幕流
        subtitle_streams = []
        for s in streams:
            codec = s.get("codec_name", "unknown")
            tags = s.get("tags", {})
            subtitle_streams.append({
                "index": s.get("index", 0),
                "codec": codec,
                "language": tags.get("language", "unknown"),
                "title": tags.get("title", ""),
                "text_based": codec in _TEXT_SUBTITLE_CODECS
            })

        text_streams = [s for s in subtitle_streams if s["text_based"]]
        image_streams = [s for s in subtitle_streams if not s["text_based"]]

        if not text_streams:
            image_names = ", ".join(s["codec"] for s in image_streams)
            return {
                "found": True, "streams": subtitle_streams, "extracted": None,
                "message": f"内嵌字幕为图像格式（{image_names}），无法直接提取文本，请使用 Whisper 转录"
            }

        # 2. 选择字幕流并提取
        if stream_index >= len(text_streams):
            stream_index = 0
        target = text_streams[stream_index]

        srt_path = temp_dir / f"extracted_{video.filename}.srt"
        ffmpeg_path = _get_bin_path("ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        extract_cmd = [
            ffmpeg_path, "-y",
            "-i", str(video_path),
            "-map", f"0:s:{stream_index}",
            "-f", "srt",
            str(srt_path)
        ]
        subprocess.run(extract_cmd, capture_output=True, encoding='utf-8', errors='replace', timeout=60, **_NO_WINDOW)

        if not srt_path.exists() or srt_path.stat().st_size == 0:
            return {
                "found": True, "streams": subtitle_streams, "extracted": None,
                "message": "提取字幕失败，请尝试 Whisper 转录"
            }

        # 3. 解析字幕
        import_subtitles = parse_srt(str(srt_path))
        original_count = len(import_subtitles)
        import_subtitles = filter_short_subtitles(import_subtitles, min_duration)

        subtitle_items = [SubtitleItem.from_subtitle(sub) for sub in import_subtitles]

        return {
            "found": True,
            "streams": subtitle_streams,
            "extracted": {
                "stream_index": target["index"],
                "codec": target["codec"],
                "language": target["language"],
                "subtitles": [s.model_dump() for s in subtitle_items],
                "total": original_count,
                "filtered": len(subtitle_items)
            },
            "message": f"已从视频提取 {len(subtitle_items)} 条内嵌字幕"
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


LANGUAGE_NAMES = {
    "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "it": "意大利语",
    "pt": "葡萄牙语", "ru": "俄语", "ar": "阿拉伯语", "th": "泰语",
    "vi": "越南语", "nl": "荷兰语", "sv": "瑞典语", "pl": "波兰语",
    "tr": "土耳其语", "hi": "印地语", "id": "印尼语", "uk": "乌克兰语",
}

DEFAULT_CRITERIA = """你是{source_language}学习教材编写专家。对输入的字幕列表，每条判断是否值得作为学习材料：

判断标准：
- 有明确的语法知识点（如时态、从句、虚拟语气等）
- 有实用表达或固定搭配
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）
- 有文化背景或情境意义"""

RETURN_FORMAT = """

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "include": true/false, "reason": "简短原因", "translation": "{target_language}翻译", "notes": "重点词汇-释义", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- include=true 表示值得加入学习
- include=false 时 reason 说明原因（如：纯简单应答、无知识价值）
- 只对 include=true 的句子提供 translation、notes、word、definition
- word 为句子中最值得背诵的核心单词或词组，definition 为其释义
- 如果句子没有明确的核心单词，word 和 definition 可以与 notes 中的重点词汇一致
- 保持原文顺序输出，每条都必须有 index 字段"""


def _get_lang_name(code: str) -> str:
    """根据语言代码获取显示名称，未知代码直接返回原代码"""
    return LANGUAGE_NAMES.get(code, code)


def _build_system_prompt(custom_prompt: str = None, source_language: str = "en", target_language: str = "zh") -> str:
    """组合用户自定义的判断标准与固定的返回格式，支持语言参数化"""
    src_name = _get_lang_name(source_language)
    tgt_name = _get_lang_name(target_language)
    if custom_prompt:
        criteria = custom_prompt
    else:
        criteria = DEFAULT_CRITERIA.format(source_language=src_name)
    formatted_format = RETURN_FORMAT.format(target_language=tgt_name)
    return criteria + formatted_format


# ─────────────────── 两阶段 AI：筛选专用提示词 ───────────────────

SCREENING_CRITERIA = """你是{source_language}学习材料筛选专家。对输入的字幕列表，每条判断是否值得作为学习材料：

判断标准：
- 有明确的语法知识点（如时态、从句、虚拟语气等）
- 有实用表达或固定搭配
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）
- 有文化背景或情境意义"""

SCREENING_RETURN_FORMAT = """

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "include": true/false, "reason": "简短原因"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- include=true 表示值得加入学习
- include=false 时 reason 说明原因（如：纯简单应答、无知识价值）
- 保持原文顺序输出，每条都必须有 index 字段"""


def _build_screening_prompt(custom_prompt: str = None, source_language: str = "en", target_language: str = "zh") -> str:
    """构建筛选专用提示词（只判断 include/reason，不返回翻译注释）"""
    src_name = _get_lang_name(source_language)
    tgt_name = _get_lang_name(target_language)
    criteria = custom_prompt if custom_prompt else SCREENING_CRITERIA.format(source_language=src_name)
    return criteria + SCREENING_RETURN_FORMAT.format(target_language=tgt_name)


# ─────────────────── 两阶段 AI：注释专用提示词 ───────────────────

# 注释标准（用户可自定义部分）
ANNOTATION_GRAMMAR_CRITERIA = """你是{source_language}学习教材编写专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和语法句型注释。"""

ANNOTATION_VOCAB_CRITERIA = """你是{target_language}词汇教学专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和词汇注释。"""

# 返回格式（固定，后端自动追加，不暴露给用户修改）
ANNOTATION_GRAMMAR_RETURN_FORMAT = """
返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "语法知识点和实用表达", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 应侧重语法结构和实用表达
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出"""

ANNOTATION_VOCAB_RETURN_FORMAT = """
返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "重点单词-词性-释义", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 格式：重点单词-词性-释义；遇词组则整体标注
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出"""


def _build_annotation_prompt(purpose: str, source_language: str = "en", target_language: str = "zh",
                             custom_criteria: str = None) -> str:
    """构建注释专用提示词：用户标准 + 后端追加固定返回格式"""
    src_name = _get_lang_name(source_language)
    tgt_name = _get_lang_name(target_language)
    if purpose == "vocab":
        criteria = custom_criteria if custom_criteria else ANNOTATION_VOCAB_CRITERIA
        criteria = criteria.format(source_language=src_name, target_language=tgt_name)
        return_format = ANNOTATION_VOCAB_RETURN_FORMAT.format(target_language=tgt_name)
    else:
        criteria = custom_criteria if custom_criteria else ANNOTATION_GRAMMAR_CRITERIA
        criteria = criteria.format(source_language=src_name, target_language=tgt_name)
        return_format = ANNOTATION_GRAMMAR_RETURN_FORMAT.format(target_language=tgt_name)
    return criteria + return_format


# AI 推荐任务进度存储
import threading as _threading
import uuid as _uuid

_recommend_store: dict = {}
_recommend_lock = _threading.Lock()


# AI 批次调用常量
_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 5, 10]  # 秒


def _parse_ai_items(parsed) -> list:
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


def _call_ai_batch(client, system_prompt: str, batch: list, model_name: str) -> tuple[list, str]:
    """
    调用 AI API 处理单批次（含重试）。

    Returns:
        (items, error): items 为结果列表，error 为空字符串表示成功，否则为错误信息
    """
    import time as _time

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            items = _parse_ai_items(parsed)
            return items, ""
        except Exception as e:
            _, last_error = translate_error(e)
            if is_transient(e) and attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt]
                _time.sleep(delay)
            else:
                return [], last_error
    return [], last_error


def _dynamic_batches(subtitle_dicts: list, max_chars: int = 3000) -> list[list]:
    """按字符数动态分批，避免长短不一导致的负载不均"""
    batches = []
    current_batch = []
    current_chars = 0

    for item in subtitle_dicts:
        item_chars = len(item.get("text", ""))
        # 单条超长字幕单独成批
        if item_chars > max_chars:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            batches.append([item])
            continue
        # 累加超过阈值则切新批
        if current_batch and current_chars + item_chars > max_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += item_chars

    if current_batch:
        batches.append(current_batch)

    return batches


async def _call_ai_batch_async(client, system_prompt: str, batch: list, model_name: str,
                               semaphore: asyncio.Semaphore) -> tuple[list, str]:
    """
    异步调用 AI API 处理单批次（指数退避抖动重试，SDK 自带 30s 超时）。
    """
    import random

    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with semaphore:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    timeout=90.0,
                )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            items = _parse_ai_items(parsed)
            # 确保每条都有必需字段
            for i, item in enumerate(items):
                if "index" not in item:
                    item["index"] = batch[i]["index"] if i < len(batch) else 0
                if "include" not in item:
                    item["include"] = False
                if "reason" not in item:
                    item["reason"] = ""
            included = sum(1 for i in items if i.get("include"))
            print(f"    AI 返回 {len(items)} 条，推荐 {included} 条")
            return items, ""
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            _, last_error = translate_error(e)
            if is_transient(e) and attempt < _MAX_RETRIES:
                delay = min(2 ** attempt + random.random(), 30)
                print(f"    批次重试 {attempt+1}/{_MAX_RETRIES}，等待 {delay:.1f}s: {err_msg}")
                await asyncio.sleep(delay)
            else:
                return [], last_error
    return [], last_error


def _run_ai_recommend(task_id: str, subtitle_dicts: list, api_key: str, system_prompt: str,
                      batch_size: int = 30, api_base: str = "https://api.deepseek.com",
                      model_name: str = "deepseek-chat"):
    """同步执行 AI 推荐（后台线程，带重试机制）"""
    from openai import OpenAI
    try:
        client = OpenAI(api_key=api_key, base_url=api_base)
    except Exception as e:
        error_code, error_msg = translate_error(e)
        with _recommend_lock:
            _recommend_store[task_id] = {
                "status": "error",
                "message": error_msg,
                "error": error_msg,
                "error_code": error_code.value
            }
        return
    results = []
    batch_size = max(1, min(100, batch_size))
    total_batches = (len(subtitle_dicts) + batch_size - 1) // batch_size
    failed_batches = 0

    with _recommend_lock:
        _recommend_store[task_id] = {
            "status": "processing",
            "batch": 0,
            "total_batches": total_batches,
            "message": "开始分析..."
        }

    try:
        for i in range(0, len(subtitle_dicts), batch_size):
            batch = subtitle_dicts[i:i + batch_size]
            batch_num = i // batch_size + 1
            msg = f"处理第 {batch_num}/{total_batches} 批 ({len(batch)} 条)..."
            print(f"  AI 推荐：{msg}")

            with _recommend_lock:
                _recommend_store[task_id].update({
                    "batch": batch_num,
                    "total_batches": total_batches,
                    "message": msg
                })

            items, error = _call_ai_batch(client, system_prompt, batch, model_name)
            if items:
                results.extend(items)
            else:
                failed_batches += 1
                reason = f"处理失败: {error}"
                print(f"    批次 {batch_num} 最终失败: {error}")
                for item in batch:
                    results.append({"index": item["index"], "include": False, "reason": reason})

        # 构建最终推荐结果
        recommendations = []
        for item in results:
            recommendations.append(AIRecommendItem(
                index=item.get("index", 0),
                include=item.get("include", False),
                reason=item.get("reason", ""),
                translation=item.get("translation") if item.get("include") else None,
                notes=item.get("notes") if item.get("include") else None,
                word=item.get("word") if item.get("include") else None,
                definition=item.get("definition") if item.get("include") else None
            ))

        finish_msg = f"分析完成，共 {len(recommendations)} 条"
        if failed_batches > 0:
            finish_msg += f"（{failed_batches} 批失败）"

        with _recommend_lock:
            _recommend_store[task_id].update({
                "status": "completed",
                "batch": total_batches,
                "message": finish_msg,
                "result": AIRecommendResponse(recommendations=recommendations).model_dump()
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_code, error_msg = translate_error(e)
        with _recommend_lock:
            _recommend_store[task_id].update({
                "status": "error",
                "message": error_msg,
                "error": error_msg,
                "error_code": error_code.value
            })


@router.post("/ai-recommend")
async def ai_recommend(request: AIRecommendRequest):
    """
    AI 分析字幕，推荐值得学习的句子（后台异步，通过 progress 端点轮询）
    """
    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    system_prompt = _build_system_prompt(request.custom_prompt, request.source_language, request.target_language)

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]

    api_base = request.api_base or "https://api.deepseek.com"
    model_name = request.model_name or "deepseek-chat"

    task_id = str(_uuid.uuid4())

    # 在后台线程中执行
    thread = _threading.Thread(
        target=_run_ai_recommend,
        args=(task_id, subtitle_dicts, api_key, system_prompt, request.batch_size,
              api_base, model_name),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id, "status": "started"}


@router.get("/ai-recommend/progress/{task_id}")
async def ai_recommend_progress(task_id: str):
    """获取 AI 推荐的实时处理进度"""
    with _recommend_lock:
        task = _recommend_store.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return task


@router.post("/ai-recommend-stream")
async def ai_recommend_stream(request: AIRecommendRequest):
    """AI 推荐 — 全异步 SSE 流式返回每批结果"""
    from openai import AsyncOpenAI

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    system_prompt = _build_system_prompt(request.custom_prompt, request.source_language, request.target_language)
    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]
    api_base = request.api_base or "https://api.deepseek.com"
    model_name = request.model_name or "deepseek-chat"

    # 动态分批（按字符数）
    batches = _dynamic_batches(subtitle_dicts, max_chars=1500)
    total_batches = len(batches)
    # 编号
    numbered_batches = [(i + 1, b) for i, b in enumerate(batches)]

    semaphore = asyncio.Semaphore(3)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        yield f"data: {json.dumps({'type': 'start', 'total_batches': total_batches})}\n\n"

        # wrapper：结果自带批次号和原始数据
        async def run_batch(num: int, batch: list):
            items, error = await _call_ai_batch_async(client, system_prompt, batch, model_name, semaphore)
            return num, batch, items, error

        tasks = [asyncio.create_task(run_batch(num, batch)) for num, batch in numbered_batches]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            num, batch, items, error = await coro
            if not items:
                items = [{"index": item["index"], "include": False, "reason": f"处理失败: {error}"} for item in batch]
            completed += 1
            print(f"  AI 推荐流式：第 {num}/{total_batches} 批完成 ({completed}/{total_batches})")
            yield f"data: {json.dumps({'type': 'batch', 'batch': num, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/ai-screen-stream")
async def ai_screen_stream(request: AIRecommendRequest):
    """AI 筛选 — 只返回 include/reason，不做翻译注释（第一阶段）"""
    from openai import AsyncOpenAI

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    system_prompt = _build_screening_prompt(request.custom_prompt, request.source_language, request.target_language)
    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]
    api_base = request.api_base or "https://api.deepseek.com"
    model_name = request.model_name or "deepseek-chat"

    batches = _dynamic_batches(subtitle_dicts, max_chars=1500)
    total_batches = len(batches)
    numbered_batches = [(i + 1, b) for i, b in enumerate(batches)]

    semaphore = asyncio.Semaphore(3)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        yield f"data: {json.dumps({'type': 'start', 'total_batches': total_batches})}\n\n"

        async def run_batch(num: int, batch: list):
            items, error = await _call_ai_batch_async(client, system_prompt, batch, model_name, semaphore)
            return num, batch, items, error

        tasks = [asyncio.create_task(run_batch(num, batch)) for num, batch in numbered_batches]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            num, batch, items, error = await coro
            if not items:
                items = [{"index": item["index"], "include": False, "reason": f"处理失败: {error}"} for item in batch]
            # 筛选模式：只保留 include 和 reason，剥离注释字段
            for item in items:
                item.pop("translation", None)
                item.pop("notes", None)
                item.pop("word", None)
                item.pop("definition", None)
            completed += 1
            print(f"  AI 筛选流式：第 {num}/{total_batches} 批完成 ({completed}/{total_batches})")
            yield f"data: {json.dumps({'type': 'batch', 'batch': num, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/ai-annotate-stream")
async def ai_annotate_stream(request: AIAnnotateRequest):
    """AI 注释 — 根据用途（语法/词汇）为已筛选字幕生成翻译和注释（第二阶段）"""
    from openai import AsyncOpenAI

    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="需要提供 API Key")

    system_prompt = _build_annotation_prompt(request.purpose, request.source_language, request.target_language, request.custom_prompt)
    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in request.subtitles
    ]
    api_base = request.api_base or "https://api.deepseek.com"
    model_name = request.model_name or "deepseek-chat"

    batches = _dynamic_batches(subtitle_dicts, max_chars=1500)
    total_batches = len(batches)
    numbered_batches = [(i + 1, b) for i, b in enumerate(batches)]

    semaphore = asyncio.Semaphore(3)

    async def event_generator():
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        yield f"data: {json.dumps({'type': 'start', 'total_batches': total_batches})}\n\n"

        async def run_batch(num: int, batch: list):
            items, error = await _call_ai_batch_async(client, system_prompt, batch, model_name, semaphore)
            return num, batch, items, error

        tasks = [asyncio.create_task(run_batch(num, batch)) for num, batch in numbered_batches]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            num, batch, items, error = await coro
            if not items:
                items = [{"index": item["index"], "translation": "", "notes": "", "word": "", "definition": ""} for item in batch]
            completed += 1
            print(f"  AI 注释流式：第 {num}/{total_batches} 批完成 ({completed}/{total_batches})")
            yield f"data: {json.dumps({'type': 'batch', 'batch': num, 'items': items}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# 转录任务进度存储
_transcribe_store: dict = {}
_transcribe_lock = _threading.Lock()
_MAX_WHISPER_SECONDS = 1800  # 30 分钟超时

# 项目根目录（用于子进程设置 sys.path）
if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = sys._MEIPASS
else:
    _PROJECT_ROOT = str(Path(__file__).parent.parent.parent)


def _whisper_subprocess(video_path: str, srt_path: str, model_name: str, language: str,
                        result_path: str, progress_pipe):
    """在独立进程中运行 Whisper 转录，通过 Pipe 报告进度（含错误）"""
    import sys as _sys
    import traceback as _traceback
    _sys.path.append(_PROJECT_ROOT)

    try:
        from core.whisper_manager import load_model
        from core.whisper_transcribe import save_as_srt
        from core.media_cut import get_video_duration

        progress_pipe.send({"step": "loading", "message": f"加载 {model_name} 模型..."})
        model = load_model(model_name)
        if model is None:
            raise RuntimeError("Whisper 未安装，请先安装 Whisper")

        # 获取视频总时长，用于计算转录进度百分比
        try:
            duration_sec = get_video_duration(video_path)
        except Exception:
            duration_sec = 0.0

        progress_pipe.send({"step": "transcribing", "message": "转录中...", "duration_sec": duration_sec})
        segments_iter, info = model.transcribe(
            video_path,
            language=language,
            word_timestamps=True,
            vad_filter=True,
        )

        segments = []
        for seg in segments_iter:
            text = seg.text.strip()
            if text:
                segments.append({"start": seg.start, "end": seg.end, "text": text})
                # 逐段上报进度
                progress = min(seg.end / duration_sec, 1.0) if duration_sec > 0 else 0.0
                progress_pipe.send({
                    "step": "transcribing",
                    "progress": progress,
                    "transcribed_sec": seg.end,
                    "duration_sec": duration_sec,
                    "text": text,
                })

        save_as_srt(segments, srt_path)

        progress_pipe.send({"step": "done", "segment_count": len(segments)})

        # 保存转录元信息到临时 JSON，供主进程读取
        import json as _json
        with open(result_path, "w", encoding="utf-8") as f:
            _json.dump({"segment_count": len(segments)}, f)

    except Exception as e:
        # 通过 pipe 将真实错误传回父进程，避免父进程只能看到 exitcode
        progress_pipe.send({
            "step": "error",
            "error": str(e),
            "traceback": _traceback.format_exc(),
        })
        raise


def _run_transcribe_task(task_id: str, video_path_str: str, srt_path_str: str,
                         model_name: str, language: str, min_duration: float):
    """后台执行转录"""
    import multiprocessing
    import time as _time

    def update(status, step, message):
        with _transcribe_lock:
            store = _transcribe_store.get(task_id, {})
            store.update({"status": status, "step": step, "total_steps": 4, "message": message})
            _transcribe_store[task_id] = store

    result_json_path = str(Path(video_path_str).with_suffix(".result.json"))
    proc = None
    _subprocess_error = None  # 子进程通过 pipe 传回的错误信息

    try:
        update("processing", 1, "准备转录...")

        # 用 Pipe 从子进程接收进度
        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)

        proc = multiprocessing.Process(
            target=_whisper_subprocess,
            args=(str(video_path_str), str(srt_path_str), model_name, language,
                  result_json_path, child_conn),
            daemon=True
        )
        proc.start()
        child_conn.close()  # 父端不写，关闭子端引用

        # 存储 proc 引用，供 cancel 端点使用
        with _transcribe_lock:
            store = _transcribe_store.get(task_id, {})
            store["_proc"] = proc
            _transcribe_store[task_id] = store

        transcribe_start = _time.time()
        last_activity = transcribe_start
        timed_out = False
        cancelled = False

        while proc.is_alive():
            # 检查是否被取消
            with _transcribe_lock:
                if _transcribe_store.get(task_id, {}).get("_cancelled"):
                    cancelled = True
                    break

            # 超时看门狗
            elapsed_total = _time.time() - transcribe_start
            if elapsed_total > _MAX_WHISPER_SECONDS:
                timed_out = True
                break

            if parent_conn.poll(1):
                try:
                    msg = parent_conn.recv()
                    last_activity = _time.time()
                    step = msg.get("step")
                    if step == "loading":
                        update("processing", 1, msg.get("message", "加载模型中..."))
                    elif step == "transcribing":
                        if "progress" in msg:
                            # 逐段进度：存 whisper_progress 供前端读取
                            with _transcribe_lock:
                                store = _transcribe_store.get(task_id, {})
                                store["whisper_progress"] = {
                                    "progress": msg["progress"],
                                    "transcribed_sec": msg["transcribed_sec"],
                                    "duration_sec": msg["duration_sec"],
                                    "text": msg.get("text", ""),
                                }
                                _transcribe_store[task_id] = store
                        else:
                            update("processing", 2, "转录中，请耐心等待...")
                    elif step == "error":
                        _subprocess_error = msg.get("error", "转录子进程异常退出")
                        break
                    elif step == "done":
                        break
                except (EOFError, OSError):
                    break
            else:
                # 无进度消息时显示已用时间
                elapsed = int(_time.time() - transcribe_start)
                mins, secs = elapsed // 60, elapsed % 60
                update("processing", 2, f"转录中... 已用时 {mins}分{secs}秒")

        # 终止子进程（超时或取消时）
        if timed_out or cancelled:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
                if proc.is_alive():
                    proc.kill()
            reason = "转录超时（超过 30 分钟）" if timed_out else "转录已取消"
            raise RuntimeError(reason)

        proc.join(timeout=30)

        # 优先使用子进程通过 pipe 传回的真实错误
        if _subprocess_error:
            raise RuntimeError(_subprocess_error)
        if proc.exitcode != 0:
            raise RuntimeError(f"转录子进程异常退出 (code={proc.exitcode})")

        update("processing", 3, "解析生成的字幕...")

        subtitles = parse_srt(str(srt_path_str))
        original_count = len(subtitles)
        subtitles = filter_short_subtitles(subtitles, min_duration)

        subtitle_items = [SubtitleItem.from_subtitle(sub) for sub in subtitles]

        with _transcribe_lock:
            _transcribe_store[task_id] = {
                "status": "completed",
                "step": 4,
                "total_steps": 4,
                "message": f"转录完成，共 {len(subtitle_items)} 条字幕",
                "result": {
                    "subtitles": [s.model_dump() for s in subtitle_items],
                    "total": original_count,
                    "filtered": len(subtitle_items)
                }
            }

    except Exception as e:
        error_code, error_msg = translate_error(e)
        with _transcribe_lock:
            _transcribe_store[task_id] = {
                "status": "error",
                "step": 0,
                "total_steps": 4,
                "message": f"转录失败: {error_msg}",
                "error": error_msg,
                "error_code": error_code.value
            }

    finally:
        # 确保子进程已终止
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
        # 清理 store 中的内部引用
        with _transcribe_lock:
            store = _transcribe_store.get(task_id, {})
            store.pop("_proc", None)
            store.pop("_cancelled", None)
        # 清理临时文件
        if Path(video_path_str).exists():
            Path(video_path_str).unlink(missing_ok=True)
        if Path(srt_path_str).exists():
            Path(srt_path_str).unlink(missing_ok=True)
        if Path(result_json_path).exists():
            Path(result_json_path).unlink(missing_ok=True)


def _check_ffmpeg_installed() -> dict:
    """检测 ffmpeg 是否已安装"""
    ffmpeg_path = _get_bin_path("ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            encoding='utf-8', errors='replace',
            timeout=5,
            **_NO_WINDOW
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0] if result.stdout else ""
            return {"installed": True, "version": version_line, "path": ffmpeg_path}
        return {"installed": False, "version": None, "path": ffmpeg_path, "reason": "ffmpeg 执行返回非零退出码"}
    except FileNotFoundError:
        return {"installed": False, "version": None, "path": ffmpeg_path, "reason": "未找到 ffmpeg 可执行文件"}
    except subprocess.TimeoutExpired:
        return {"installed": False, "version": None, "path": ffmpeg_path, "reason": "ffmpeg 响应超时"}
    except Exception as e:
        return {"installed": False, "version": None, "path": ffmpeg_path, "reason": str(e)[:200]}


@router.get("/ffmpeg/status")
async def ffmpeg_status():
    """检查 ffmpeg 是否已安装"""
    return _check_ffmpeg_installed()


@router.get("/whisper/status")
async def whisper_status():
    """检查 Whisper 是否已安装"""
    installed = is_whisper_installed()
    if installed:
        return {"installed": True, "mode": "ok"}
    # 非打包环境提示 pip 安装，打包环境提示下载插件
    mode = "dev" if not getattr(sys, 'frozen', False) else "frozen"
    return {"installed": False, "mode": mode}


@router.post("/whisper/install")
async def whisper_install():
    """
    安装 Whisper（CPU 版本，约 200MB）
    首次使用语音转录功能时调用
    """
    if is_whisper_installed():
        return {"status": "already_installed", "message": "Whisper 已安装"}

    success, error = install_whisper()
    if success:
        return {"status": "success", "message": "Whisper 安装成功"}
    else:
        raise HTTPException(status_code=500, detail=f"Whisper 安装失败: {error}")


@router.post("/transcribe")
async def transcribe_video_endpoint(
    video: UploadFile = File(...),
    min_duration: float = 1.0,
    language: Optional[str] = None,
    model_name: str = "base"
):
    """
    使用 Whisper 将视频转录为字幕（后台异步，通过 progress 端点轮询）
    """
    # 检查 Whisper 是否已安装
    if not is_whisper_installed():
        raise HTTPException(
            status_code=400,
            detail="Whisper 未安装，请先调用 POST /api/subtitles/whisper/install 安装"
        )

    if not video.filename:
        raise HTTPException(status_code=400, detail="未提供视频文件")

    temp_dir = _get_temp_dir()
    video_path = temp_dir / f"transcribe_{video.filename}"
    srt_path = temp_dir / f"transcribe_{video.filename}.srt"

    with open(video_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    task_id = str(_uuid.uuid4())

    with _transcribe_lock:
        _transcribe_store[task_id] = {
            "status": "preparing",
            "step": 0,
            "total_steps": 4,
            "message": "准备转录..."
        }

    thread = _threading.Thread(
        target=_run_transcribe_task,
        args=(task_id, str(video_path), str(srt_path), model_name, language, min_duration),
        daemon=True
    )
    thread.start()

    return {"task_id": task_id, "status": "started"}


@router.get("/transcribe/progress/{task_id}")
async def transcribe_progress(task_id: str):
    """获取转录实时进度"""
    with _transcribe_lock:
        task = _transcribe_store.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 过滤内部字段（_proc, _cancelled 等不可序列化的引用）
    return {k: v for k, v in task.items() if not k.startswith("_")}


@router.post("/transcribe/cancel/{task_id}")
async def cancel_transcribe(task_id: str):
    """取消正在进行的转录任务"""
    with _transcribe_lock:
        task = _transcribe_store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        task["_cancelled"] = True
        proc = task.get("_proc")

    # 尝试立即终止子进程
    if proc is not None and proc.is_alive():
        proc.terminate()

    return {"status": "cancelling", "message": "转录取消中..."}


@router.get("/example", response_model=SubtitleListResponse)
async def get_example_subtitles():
    """
    获取示例字幕数据（用于前端演示）
    """
    example_data = [
        SubtitleItem(
            index=1,
            start_sec=83.456,
            end_sec=85.789,
            text="Hello, how are you?",
            duration=2.333
        ),
        SubtitleItem(
            index=2,
            start_sec=86.123,
            end_sec=89.456,
            text="I'm doing great, thanks for asking!",
            duration=3.333
        ),
        SubtitleItem(
            index=3,
            start_sec=90.123,
            end_sec=94.567,
            text="What have you been up to lately?",
            duration=4.444
        )
    ]

    return SubtitleListResponse(
        subtitles=example_data,
        total=3,
        filtered=3
    )


@router.get("/learned-words")
async def get_learned_words():
    """返回已学单词列表，供前端过滤"""
    from services.progress import get_learned_words, get_learned_count
    words = get_learned_words()
    return {"words": words, "count": len(words)}


@router.post("/sync-learned-from-anki")
async def sync_learned_from_anki(body: dict):
    """从 Anki 同步已学词汇到本地数据库"""
    from services.progress import mark_words_learned, get_learned_count
    words = body.get("words", [])
    if not words:
        return {"synced": 0, "total": get_learned_count()}
    word_dicts = [{"word": w, "definition": ""} for w in words if isinstance(w, str) and w.strip()]
    mark_words_learned(word_dicts, source_video="anki-sync")
    return {"synced": len(word_dicts), "total": get_learned_count()}
