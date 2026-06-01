"""
处理相关 API - 处理字幕并生成卡片
支持多视频上传：合并模式（一个牌组）或独立模式（多个牌组）
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse
from pathlib import Path
from typing import List, Optional
import asyncio
import json
import os
import shutil
import threading
import uuid
import asyncio
import zipfile
import tempfile
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from models.schemas import ProcessRequest, ProcessResult, ProcessedCard, ProcessProgress

# 导入现有模块
import sys
if getattr(sys, 'frozen', False):
    # PyInstaller 打包环境
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import run as process_cards, generate_apkg, _process_video_to_media
from .prompts import build_screening_prompt as _build_screening_prompt, build_annotation_prompt as _build_annotation_prompt
from models.schemas import BatchProcessRequest, BatchProcessResponse

from errors import translate_error, get_message, ErrorCode, ClipLingoError
from utils.zip_export import generate_csv_with_media_paths

router = APIRouter()

# 临时文件存储目录（打包后使用 %APPDATA% 避免权限问题）
if getattr(sys, 'frozen', False):
    TEMP_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo' / 'temp'
else:
    TEMP_DIR = Path(__file__).parent.parent.parent / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 任务进度存储 (task_id -> progress dict)
task_store: dict = {}
task_store_lock = threading.Lock()


def _to_url(file_path: str) -> str:
    """将绝对文件路径转为 /output/... 的 HTTP URL"""
    if not file_path:
        return None
    p = Path(file_path)
    parts = p.parts
    for i, part in enumerate(parts):
        if part == "output":
            return "/output/" + "/".join(parts[i+1:])
    return "/output/" + p.parent.name + "/" + p.name


def _build_cards(processed_data):
    """将处理数据转为 ProcessedCard 列表，文件路径转为 HTTP URL"""
    cards = []
    for item in processed_data:
        cards.append(ProcessedCard(
            sentence=item.get("text", ""),
            translation=item.get("translation", ""),
            notes=item.get("notes", ""),
            word=item.get("word", ""),
            definition=item.get("definition", ""),
            start_sec=item.get("start_sec", 0),
            end_sec=item.get("end_sec", 0),
            audio_path=_to_url(item.get("audio_path")),
            screenshot_path=_to_url(item.get("screenshot_path"))
        ))
    return cards


@router.post("/upload-and-process")
async def upload_and_process(
    videos: list[UploadFile] = File(...),
    subtitles: list[UploadFile] = File(default=[]),
    merge: bool = Form(True),
    min_duration: float = Form(1.0),
    output_dir: str = Form(None),
    api_key: Optional[str] = Form(None),
    api_base: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
    pre_processed: Optional[str] = Form(None),
    padding_start_ms: int = Form(200),
    padding_end_ms: int = Form(200),
    card_styles: Optional[str] = Form(None),
    theme: str = Form("default"),
    theme_overrides: Optional[str] = Form(None),
    source_language: str = Form("en"),
    target_language: str = Form("zh"),
    screen_prompt_criteria: Optional[str] = Form(None),
    annotation_purpose: Optional[str] = Form(None),
    annotation_prompt_criteria: Optional[str] = Form(None),
    select_recommended_only: bool = Form(False),
    stop_after_media: bool = Form(False),
    mt_service: Optional[str] = Form(None),
    mt_api_key: Optional[str] = Form(None),
    mt_api_base: Optional[str] = Form(None),
    mt_model_name: Optional[str] = Form(None),
):
    """
    上传视频和字幕文件，后台异步处理

    支持多个视频：
    - merge=True（默认）：所有视频合并到一个 Anki 牌组
    - merge=False：每个视频独立生成牌组
    - stop_after_media=True：仅处理媒体不打包，状态变为 awaiting_styles，之后调 /generate-apkg 完成打包

    返回 task_id，前端通过 /progress/{task_id} 轮询进度
    """
    if not videos:
        raise HTTPException(status_code=400, detail="至少需要一个视频文件")

    task_id = str(uuid.uuid4())

    # 每个任务使用独立的 output_dir
    if output_dir is None:
        if getattr(sys, 'frozen', False):
            base_output = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo' / 'output'
        else:
            base_output = Path(__file__).parent.parent.parent / "output"
    else:
        base_output = Path(output_dir)
    output_dir = str(base_output / task_id)

    task_dir = TEMP_DIR / task_id
    task_dir.mkdir(exist_ok=True)

    # 保存所有上传的文件（视频存到 videos/ 子目录，供批处理复用）
    videos_subdir = task_dir / "videos"
    videos_subdir.mkdir(exist_ok=True)

    video_paths = []
    subtitle_paths = []
    video_names = []

    for i, video in enumerate(videos):
        v_path = videos_subdir / video.filename
        with open(v_path, "wb") as f:
            shutil.copyfileobj(video.file, f)
        video_paths.append(str(v_path))
        video_names.append(video.filename)

    for i, subtitle in enumerate(subtitles):
        if subtitle.filename:
            s_path = task_dir / subtitle.filename
            with open(s_path, "wb") as f:
                shutil.copyfileobj(subtitle.file, f)
            # 空文件（0 字节）视为未提供字幕，后端走 Whisper 转录
            if s_path.stat().st_size == 0:
                subtitle_paths.append("")
            else:
                subtitle_paths.append(str(s_path))
        else:
            subtitle_paths.append("")

    # 补齐 subtitle_paths 长度
    while len(subtitle_paths) < len(video_paths):
        subtitle_paths.append("")

    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key

    # 解析预处理数据
    pre_processed_data = None
    if pre_processed:
        try:
            pre_processed_data = json.loads(pre_processed)
        except json.JSONDecodeError:
            pass

    # 解析卡片样式
    card_styles_list = None
    if card_styles:
        try:
            card_styles_list = json.loads(card_styles)
        except json.JSONDecodeError:
            card_styles_list = [card_styles]

    # 解析主题覆盖变量
    theme_overrides_dict = None
    if theme_overrides:
        try:
            theme_overrides_dict = json.loads(theme_overrides)
        except json.JSONDecodeError:
            pass

    # 初始化任务进度
    with task_store_lock:
        task_store[task_id] = {
            "status": "preparing",
            "step": 0,
            "total_steps": 5,
            "message": f"准备处理 {len(videos)} 个视频...",
            "details": None,
            "result": None,
            "error": None,
            "error_code": None,
            "output_dir": output_dir,
            "merge": merge,
            "total_videos": len(videos),
            "select_recommended_only": select_recommended_only,
            # 上传序的视频名列表：批处理据此定位 video_{idx}_selected.srt，
            # 避免用 videos_dir 字典序索引导致字幕错配
            "video_names_order": list(video_names),
        }

    def progress_callback(step, total_steps, message, details=None):
        with task_store_lock:
            task_store[task_id].update({
                "status": "processing",
                "step": step,
                "total_steps": total_steps,
                "message": message,
                "details": details
            })

    def run_processing():
        try:
            with task_store_lock:
                task_store[task_id]["status"] = "processing"
                task_store[task_id]["message"] = "开始处理..."

            # 构建完整的 AI 提示词（前端传入的是 criteria 部分，后端补充返回格式）
            screen_full_prompt = _build_screening_prompt(
                custom_prompt=screen_prompt_criteria,
                source_language=source_language,
                target_language=target_language,
            )
            annotation_full_prompt = None
            if annotation_purpose:
                annotation_full_prompt = _build_annotation_prompt(
                    purpose=annotation_purpose,
                    source_language=source_language,
                    target_language=target_language,
                    custom_criteria=annotation_prompt_criteria,
                )

            # 构建 process_cards 参数
            process_kwargs = dict(
                video_paths=video_paths,
                subtitle_paths=[p if p else None for p in subtitle_paths],
                output_dir=output_dir,
                merge=merge,
                min_duration=min_duration,
                progress_callback=progress_callback,
                pre_processed=pre_processed_data,
                api_base=api_base,
                model_name=model_name,
                padding_start_ms=padding_start_ms,
                source_language=source_language,
                target_language=target_language,
                padding_end_ms=padding_end_ms,
                screen_system_prompt=screen_full_prompt,
                annotation_system_prompt=annotation_full_prompt,
                select_recommended_only=select_recommended_only,
                stop_after_media=stop_after_media,
                mt_service=mt_service,
                mt_api_key=mt_api_key,
                mt_api_base=mt_api_base,
                mt_model_name=mt_model_name,
            )
            # 完整模式才传样式参数；两阶段模式在 Phase 2 才传
            if not stop_after_media:
                process_kwargs.update(dict(
                    card_styles=card_styles_list,
                    theme=theme,
                    theme_overrides=theme_overrides_dict,
                ))

            result = process_cards(**process_kwargs)

            # 记录已学单词
            def _record_words(processed_list, video_name=""):
                try:
                    from services.progress import mark_words_learned
                    words_to_record = [
                        {"word": p.get("word", ""), "definition": p.get("definition", "")}
                        for p in processed_list
                        if p.get("word")
                    ]
                    if words_to_record:
                        mark_words_learned(words_to_record, source_video=video_name)
                except Exception as e:
                    print(f"记录已学单词失败（不影响主流程）: {e}")

            if stop_after_media:
                # Phase 1 完成：媒体已处理，等待用户选择样式
                if merge:
                    cards = _build_cards(result.get("processed", []))
                    _record_words(result.get("processed", []), video_names[0] if len(video_names) == 1 else "")

                    with task_store_lock:
                        task_store[task_id].update({
                            "status": "awaiting_styles",
                            "step": 3,
                            "total_steps": 5,
                            "message": f"媒体处理完成，共 {result['cards_count']} 张卡片，请选择样式",
                            "result": {
                                "success": True,
                                "message": f"媒体处理完成，共 {result['cards_count']} 张卡片",
                                "task_id": task_id,
                                "phase": "media_done",
                                "merge": True,
                                "cards_count": result["cards_count"],
                                "video_name": ", ".join(video_names),
                                "cards": [c.model_dump() for c in cards],
                            }
                        })
                else:
                    all_results = result.get("results", [])
                    flat_cards = []
                    for r in all_results:
                        for p in r.get("processed", []):
                            flat_cards.append(p)
                    cards = _build_cards(flat_cards)

                    with task_store_lock:
                        task_store[task_id].update({
                            "status": "awaiting_styles",
                            "step": 3,
                            "total_steps": 5,
                            "message": f"媒体处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片，请选择样式",
                            "result": {
                                "success": True,
                                "message": f"媒体处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片",
                                "task_id": task_id,
                                "phase": "media_done",
                                "merge": False,
                                "total_cards": result["total_cards"],
                                "cards": [c.model_dump() for c in cards],
                            }
                        })

            elif merge:
                apkg_filename = Path(result["apkg_path"]).name
                cards = _build_cards(result.get("processed", []))
                _record_words(result.get("processed", []), video_names[0] if len(video_names) == 1 else "")

                with task_store_lock:
                    task_store[task_id].update({
                        "status": "completed",
                        "step": 5,
                        "message": f"处理完成，生成了 {result['cards_count']} 张卡片",
                        "result": {
                            "success": True,
                            "message": f"处理完成，生成了 {result['cards_count']} 张卡片",
                            "task_id": task_id,
                            "cards_count": result["cards_count"],
                            "apkg_path": apkg_filename,
                            "apkg_url": f"/output/{task_id}/{apkg_filename}",
                            "video_name": ", ".join(video_names),
                            "cards": [c.model_dump() for c in cards]
                        }
                    })
            else:
                # 独立模式：返回多个牌组结果
                all_results = result.get("results", [])
                flat_cards = []
                apkg_list = []
                for r in all_results:
                    apkg_name = Path(r["apkg_path"]).name
                    apkg_list.append({
                        "video_name": r["video_name"],
                        "cards_count": r["cards_count"],
                        "apkg_path": apkg_name,
                        "apkg_url": f"/output/{task_id}/{apkg_name}",
                    })
                    for p in r.get("processed", []):
                        flat_cards.append(p)
                    _record_words(r.get("processed", []), r.get("video_name", ""))

                cards = _build_cards(flat_cards)

                with task_store_lock:
                    task_store[task_id].update({
                        "status": "completed",
                        "step": 5,
                        "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片",
                        "result": {
                            "success": True,
                            "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片",
                            "task_id": task_id,
                            "merge": False,
                            "total_cards": result["total_cards"],
                            "videos": apkg_list,
                            "cards": [c.model_dump() for c in cards]
                        }
                    })

        except Exception as e:
            import traceback
            traceback.print_exc()
            error_code, error_msg = translate_error(e)
            with task_store_lock:
                task_store[task_id].update({
                    "status": "error",
                    "message": f"处理失败: {error_msg}",
                    "error": error_msg,
                    "error_code": error_code.value
                })
        finally:
            # stop_after_media=True 时保留 task_dir（含 videos/），供批处理复用
            if not stop_after_media:
                shutil.rmtree(task_dir, ignore_errors=True)

    # 在后台线程中执行
    thread = threading.Thread(target=run_processing, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "started", "merge": merge}


@router.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """
    获取处理进度

    Args:
        task_id: 任务ID

    Returns:
        ProcessProgress: 当前处理进度
    """
    with task_store_lock:
        task = task_store.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    response = {
        "task_id": task_id,
        "status": task["status"],
        "step": task["step"],
        "total_steps": task["total_steps"],
        "message": task["message"],
        "details": task["details"],
        "error": task.get("error"),
        "error_code": task.get("error_code")
    }

    # 如果已完成或等待样式，附带结果
    if (task["status"] == "completed" or task["status"] == "awaiting_styles" or task["status"] == "packing") and task.get("result"):
        response["result"] = task["result"]
    elif task["status"] == "error":
        response["error"] = task.get("error")
        response["error_code"] = task.get("error_code")

    return response


@router.post("/generate-apkg")
async def generate_apkg_endpoint(
    task_id: str = Form(...),
    card_styles: Optional[str] = Form(None),
    theme: str = Form("default"),
    theme_overrides: Optional[str] = Form(None),
):
    """
    Phase 2: 从已处理的媒体文件生成 .apkg

    需要先完成 Phase 1（status='awaiting_styles'）。
    """
    import json as _json

    with task_store_lock:
        task = task_store.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.get("status") != "awaiting_styles":
        raise HTTPException(status_code=400, detail="任务状态不正确，需要先完成媒体处理")

    output_dir = task["output_dir"]

    # 解析样式参数
    card_styles_list = None
    if card_styles:
        try:
            card_styles_list = _json.loads(card_styles)
        except _json.JSONDecodeError:
            card_styles_list = [card_styles]

    theme_overrides_dict = None
    if theme_overrides:
        try:
            theme_overrides_dict = _json.loads(theme_overrides)
        except _json.JSONDecodeError:
            pass

    def progress_callback(step, total_steps, message, details=None):
        with task_store_lock:
            task_store[task_id].update({
                "status": "packing",
                "step": step,
                "total_steps": total_steps,
                "message": message,
                "details": details,
            })

    def run_packing():
        try:
            result = generate_apkg(
                output_dir=output_dir,
                card_styles=card_styles_list,
                theme=theme,
                theme_overrides=theme_overrides_dict,
                progress_callback=progress_callback,
            )

            # 读取 manifest 的 partial 标记：批处理中途失败会置 True，
            # 用于提示客户当前牌组不完整（仅含已成功的视频）
            is_partial = False
            try:
                _mf = Path(output_dir) / "processed_cards.json"
                if _mf.exists():
                    is_partial = bool(_json.loads(_mf.read_text(encoding="utf-8")).get("partial"))
            except Exception:
                is_partial = False
            partial_suffix = "（注意：部分视频处理失败，此牌组不完整，仅含已成功的视频）" if is_partial else ""

            is_merge = result.get("apkg_path") is not None  # merge=True 返回 apkg_path
            if is_merge:
                apkg_filename = Path(result["apkg_path"]).name
                cards = _build_cards(result.get("processed", []))
                with task_store_lock:
                    task_store[task_id].update({
                        "status": "completed",
                        "step": 1,
                        "total_steps": 2,
                        "message": f"处理完成，生成了 {result['cards_count']} 张卡片" + partial_suffix,
                        "result": {
                            "success": True,
                            "message": f"处理完成，生成了 {result['cards_count']} 张卡片" + partial_suffix,
                            "task_id": task_id,
                            "cards_count": result["cards_count"],
                            "apkg_path": apkg_filename,
                            "apkg_url": f"/output/{task_id}/{apkg_filename}",
                            "partial": is_partial,
                            "cards": [c.model_dump() for c in cards],
                        }
                    })
            else:
                all_results = result.get("results", [])
                flat_cards = []
                apkg_list = []
                for r in all_results:
                    apkg_name = Path(r["apkg_path"]).name
                    apkg_list.append({
                        "video_name": r["video_name"],
                        "cards_count": r["cards_count"],
                        "apkg_path": apkg_name,
                        "apkg_url": f"/output/{task_id}/{apkg_name}",
                    })
                    for p in r.get("processed", []):
                        flat_cards.append(p)

                cards = _build_cards(flat_cards)
                with task_store_lock:
                    task_store[task_id].update({
                        "status": "completed",
                        "step": 1,
                        "total_steps": 2,
                        "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片" + partial_suffix,
                        "result": {
                            "success": True,
                            "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片" + partial_suffix,
                            "task_id": task_id,
                            "merge": False,
                            "total_cards": result["total_cards"],
                            "videos": apkg_list,
                            "partial": is_partial,
                            "cards": [c.model_dump() for c in cards],
                        }
                    })

        except Exception as e:
            import traceback
            traceback.print_exc()
            error_code, error_msg = translate_error(e)
            with task_store_lock:
                task_store[task_id].update({
                    "status": "error",
                    "message": f"打包失败: {error_msg}",
                    "error": error_msg,
                    "error_code": error_code.value,
                })
        finally:
            # Phase 2 完成，清理 Phase 1 保留的 task_dir（含 videos/）
            task_dir = TEMP_DIR / task_id
            shutil.rmtree(task_dir, ignore_errors=True)

    thread = threading.Thread(target=run_packing, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "packing"}


@router.post("/cleanup")
async def cleanup_output(task_id: str):
    """
    下载后清理该任务的 output 目录

    Args:
        task_id: 任务 ID
    """
    with task_store_lock:
        task = task_store.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_output_dir = Path(task.get("output_dir", ""))
    cleaned = []

    if task_output_dir.exists():
        shutil.rmtree(str(task_output_dir), ignore_errors=True)
        cleaned.append(str(task_output_dir))

    # 清理 task_store 中的记录
    with task_store_lock:
        task_store.pop(task_id, None)

    return {"cleaned": cleaned}


@router.get("/export-zip/{task_id}")
async def export_zip_with_media(task_id: str):
    """导出带媒体文件的 ZIP 包（单个牌组或多牌组）"""
    with task_store_lock:
        task = task_store.get(task_id)

    if not task or task.get("status") != "completed" or not task.get("result"):
        raise HTTPException(status_code=404, detail="任务不存在或未完成")

    output_dir = Path(task["output_dir"])
    result = task["result"]
    cards = result.get("cards", [])
    video_name = result.get("video_name", "export")
    is_merge = result.get("merge", True) and "videos" not in result

    # 生成 CSV
    csv_content = generate_csv_with_media_paths(cards)

    # 创建 ZIP
    zip_path = Path(tempfile.mktemp(suffix=".zip"))
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("cards.csv", csv_content)

        audio_dir = output_dir / "audio"
        if audio_dir.exists():
            for f in audio_dir.iterdir():
                if f.is_file() and f.suffix == '.mp3':
                    zf.write(str(f), f"audio/{f.name}")

        screenshot_dir = output_dir / "screenshots"
        if screenshot_dir.exists():
            for f in screenshot_dir.iterdir():
                if f.is_file() and f.suffix == '.jpg':
                    zf.write(str(f), f"screenshots/{f.name}")

    stem = Path(video_name.split(",")[0].strip()).stem if video_name else "export"
    return FileResponse(
        str(zip_path),
        filename=f"ClipLingo_{stem}.zip",
        media_type="application/zip",
        background=None,
    )


@router.post("/start", response_model=ProcessResult)
async def start_processing(
    video_file_path: str,
    subtitle_file_path: str,
    min_duration: float = 1.0,
    output_dir: str = "./output",
    api_key: Optional[str] = None
):
    """
    开始处理视频和字幕，生成 Anki 卡片

    Args:
        video_file_path: 视频文件路径
        subtitle_file_path: 字幕文件路径
        min_duration: 最短字幕时长
        output_dir: 输出目录
        api_key: DeepSeek API Key

    Returns:
        ProcessResult: 处理结果
    """
    # 验证文件存在
    video_path = Path(video_file_path)
    subtitle_path = Path(subtitle_file_path)

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    if not subtitle_path.exists():
        raise HTTPException(status_code=404, detail="字幕文件不存在")

    # 设置 API Key
    if api_key:
        os.environ["DEEPSEEK_API_KEY"] = api_key

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            process_cards,
            [str(video_path)],
            [str(subtitle_path)],
            output_dir,
            True,  # merge single video
            api_key,  # unused, already in env
            min_duration
        )

        apkg_path = result["apkg_path"]
        cards_count = result["cards_count"]
        processed_data = result.get("processed", [])
        cards = _build_cards(processed_data)

        return ProcessResult(
            success=True,
            message=f"处理完成，生成了 {cards_count} 张卡片",
            cards_count=cards_count,
            apkg_path=apkg_path,
            cards=cards
        )

    except Exception as e:
        _, error_msg = translate_error(e)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/test-connection")
async def test_connection(
    api_key: str,
    api_base: str = "https://api.deepseek.com",
    model_name: str = "deepseek-chat"
):
    """测试 AI API 连接是否有效"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=api_base)

        client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5
        )

        return {"valid": True, "message": f"连接成功（{model_name}）"}

    except Exception as e:
        _, msg = translate_error(e)
        return {"valid": False, "message": msg}


@router.post("/list-models")
async def list_models(
    api_key: str,
    api_base: str = "https://api.deepseek.com"
):
    """获取可用模型列表"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=api_base)
        models = client.models.list()

        model_ids = sorted(
            [m.id for m in models],
            key=lambda x: (not x.startswith("deepseek"), x)
        )

        return {"models": model_ids}

    except Exception as e:
        _, error_msg = translate_error(e)
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {error_msg}")


# ─── Batch Process Endpoint ─────────────────────────────────────────────

def _sse_encode(data: dict) -> str:
    """Encode a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _persist_batch_results(output_dir: str, all_processed: list, partial: bool = False) -> None:
    """
    将已处理卡片记录已学单词并合并进 manifest（供 generate_apkg 使用）。

    成功完成与中途失败都调用：失败时持久化失败前已完成视频的结果，
    配合 stem/index 幂等去重，重试可跳过已完成视频、只重跑失败的（可恢复批处理）。

    partial=True 时在 manifest 写入 partial 标记，供打包结果提示客户「牌组不完整」；
    重试全部成功后以 partial=False 调用会清除该标记。
    """
    # 录制已学单词
    if all_processed:
        try:
            from services.progress import mark_words_learned
            words_to_record = [
                {"word": p.get("word", ""), "definition": p.get("definition", "")}
                for p in all_processed
                if p.get("word")
            ]
            if words_to_record:
                mark_words_learned(words_to_record)
        except Exception as e:
            print(f"记录已学单词失败（不影响主流程）: {e}")

    # 合并批处理结果到 manifest
    manifest_path = Path(output_dir) / "processed_cards.json"
    print(f"[批处理] 准备合并结果到 manifest: {manifest_path}")
    print(f"[批处理] 本次处理了 {len(all_processed)} 张卡片（partial={partial}）")

    if not manifest_path.exists():
        if all_processed:
            logger.warning(f"[批处理] manifest 文件不存在，无法合并: {manifest_path}")
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original_count = len(manifest.get("processed", []))
        print(f"[批处理] manifest 已存在，原有 {original_count} 张卡片")

        # 标记部分完成状态（失败置 True / 全部成功置 False），供前端与打包结果提示客户
        manifest["partial"] = partial

        if not all_processed:
            # 无新结果（如首个视频即失败）：仅更新 partial 标记后落盘
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return

        if manifest.get("merge", True):
            # 合并模式：追加到 processed 列表（按 index 去重，保证重跑幂等）
            existing_indices = {p.get("index") for p in manifest.get("processed", [])}
            new_cards = [
                p for p in all_processed
                if p.get("index") not in existing_indices
            ]
            manifest["processed"].extend(new_cards)
            print(f"[批处理] 合并后共 {len(manifest['processed'])} 张卡片")
        else:
            # 独立模式：按 video_stem 分组并追加到 results
            if "results" not in manifest:
                manifest["results"] = []

            # 已存在的视频分组，跳过以保证重跑幂等
            existing_stems = {r.get("video_name") for r in manifest["results"]}

            grouped = {}
            for p in all_processed:
                stem = p.get("video_stem", "unknown")
                grouped.setdefault(stem, []).append(p)

            for stem, items in grouped.items():
                if stem in existing_stems:
                    continue
                manifest["results"].append({
                    "video_name": stem,
                    "cards_count": len(items),
                    "processed": items,
                })

            if "total_cards" in manifest:
                manifest["total_cards"] = sum(r["cards_count"] for r in manifest["results"])

        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"[批处理] manifest 写入成功: {manifest_path}")
    except Exception as e:
        logger.error(f"[批处理] 合并结果到 manifest 失败: {e}", exc_info=True)


@router.post("/batch-process")
async def batch_process(request: BatchProcessRequest):
    """
    批量处理剩余视频 — 复用首视频的 AI 配置。

    每个视频运行完整 pipeline（Whisper → 解析 → 修正 → 筛选 → 注释 → 媒体切割），
    通过 SSE 返回逐视频进度，处理完成后返回结构化结果。
    """
    from collections import deque

    # 从 task_id 查找 temp 目录
    original_task_dir = TEMP_DIR / request.task_id
    if not original_task_dir.exists():
        return StreamingResponse(
            iter([_sse_encode({"type": "error", "message": "原始任务目录不存在"})]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    videos_dir = original_task_dir / "videos"
    if not videos_dir.exists():
        return StreamingResponse(
            iter([_sse_encode({"type": "error", "message": "未找到视频文件目录"})]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    # 只处理前端发送的剩余视频（跳过第一个，已在 Phase 1 处理）
    all_video_paths = sorted(videos_dir.iterdir())
    # 构建 视频文件名 → 上传序索引 的映射（用于查找 video_{idx}_selected.srt）。
    # 优先用 Phase 1 持久化的上传序；前端 video_{vi}_selected.srt 的 vi 即上传序，
    # 若改用 videos_dir 字典序会在「上传序 != 文件名序」时把字幕配错。
    with task_store_lock:
        _stored_task = task_store.get(request.task_id, {})
    _upload_order = _stored_task.get("video_names_order")
    if _upload_order:
        video_name_to_idx: dict[str, int] = {name: i for i, name in enumerate(_upload_order)}
    else:
        # 兼容旧任务（无持久化上传序）：回退到文件名排序索引
        video_name_to_idx = {p.name: i for i, p in enumerate(all_video_paths)}
    if request.video_names:
        # 按前端指定的文件名过滤
        video_names = [
            p for p in all_video_paths
            if p.name in request.video_names
        ]
    else:
        # 兼容旧逻辑：处理所有视频
        video_names = all_video_paths

    if len(video_names) == 0:
        return StreamingResponse(
            iter([_sse_encode({"type": "error", "message": "没有需要批量处理的视频"})]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    total_videos = len(video_names)
    output_dir = str(original_task_dir.parent.parent / "output" / request.task_id)

    # 复用首视频的 select_recommended_only 设置
    with task_store_lock:
        original_task = task_store.get(request.task_id, {})
    original_select_recommended_only = original_task.get("select_recommended_only", False)

    # 构建公共提示词
    screen_full_prompt = None
    annotation_full_prompt = None
    if request.run_screening or request.run_annotation:
        screen_full_prompt = _build_screening_prompt(
            custom_prompt=request.custom_screen_prompt,
            source_language=request.source_language,
            target_language=request.target_language,
        )

        if request.run_annotation and request.annotation_purpose:
            annotation_full_prompt = _build_annotation_prompt(
                purpose=request.annotation_purpose,
                source_language=request.source_language,
                target_language=request.target_language,
                custom_criteria=request.custom_annotation_prompt,
            )

    # 构建视频名 → 字幕文件名的精确映射（来自前端 subtitle_files）
    subtitle_map: dict[str, str] = {}
    if request.subtitle_files:
        for idx, vname in enumerate(request.video_names):
            if idx < len(request.subtitle_files) and request.subtitle_files[idx]:
                subtitle_map[vname] = request.subtitle_files[idx]

    async def event_generator():
        all_processed = []
        total_cards = 0
        successes = 0
        failures: list = []  # [{"video_index", "video_name", "message"}]

        yield _sse_encode({"type": "start", "total_videos": total_videos})

        try:
            for i, vp in enumerate(video_names):
                # 优先使用前端传递的精确字幕映射
                subtitle_path = ""
                sub_name = subtitle_map.get(vp.name)
                if sub_name:
                    sub_file = original_task_dir / sub_name
                    if sub_file.exists() and sub_file.stat().st_size > 0:
                        subtitle_path = str(sub_file)

                # 回退1：按 video_{original_index}_selected.srt 匹配（Phase 1 生成的筛选字幕）
                if not subtitle_path:
                    original_idx = video_name_to_idx.get(vp.name)
                    if original_idx is not None:
                        selected_srt = original_task_dir / f"video_{original_idx}_selected.srt"
                        if selected_srt.exists() and selected_srt.stat().st_size > 0:
                            subtitle_path = str(selected_srt)

                # 回退2：按视频 stem 匹配字幕文件
                if not subtitle_path:
                    srt_candidates = list(original_task_dir.glob(f"{vp.stem}*.*"))
                    srt_paths = [s for s in srt_candidates if s.suffix.lower() in ('.srt', '.ass', '.vtt')]
                    subtitle_path = str(srt_paths[0]) if srt_paths else ""

                # 线程池执行同步的 _process_video_to_media
                # 使用 list 代替 deque（线程安全 + 可被 async 轮询）
                progress_queue: list = []
                processing_error: list = []  # [exc] if failed
                processing_done = asyncio.Event()

                def thread_progress(step, total_steps, message, details=None):
                    progress_queue.append({"step": step, "message": message})

                def run_in_thread():
                    try:
                        result = _process_video_to_media(
                            video_path=str(vp),
                            subtitle_path=subtitle_path,
                            output_dir=output_dir,
                            index_offset=(i + 1) * 10000,
                            video_index=i + 1,
                            total_videos=total_videos + 1,
                            pre_processed=None,
                            api_key=request.api_key,
                            api_base=request.api_base,
                            model_name=request.model_name,
                            min_duration=request.min_duration,
                            padding_start_ms=200,
                            padding_end_ms=200,
                            source_language=request.source_language,
                            target_language=request.target_language,
                            screen_system_prompt=screen_full_prompt,
                            annotation_system_prompt=annotation_full_prompt,
                            select_recommended_only=original_select_recommended_only,
                            mt_service=request.mt_service,
                            mt_api_key=request.mt_api_key,
                            mt_api_base=request.mt_api_base,
                            mt_model_name=request.mt_model_name,
                            progress_callback=thread_progress,
                        )
                        # 把结果放进队列，主循环取出
                        progress_queue.append(("__result__", result))
                    except Exception as exc:
                        processing_error.append(exc)
                    finally:
                        # 线程安全：在事件循环中设置 event
                        asyncio.run_coroutine_threadsafe(
                            _set_event(processing_done),
                            loop,
                        )

                async def _set_event(ev):
                    ev.set()

                loop = asyncio.get_event_loop()
                thread = threading.Thread(target=run_in_thread, daemon=True)
                thread.start()

                # 边处理边发送进度事件（防止 SSE 超时断开）
                pp_result = None
                while not processing_done.is_set():
                    # 发送积攒的进度消息
                    while progress_queue:
                        item = progress_queue.pop(0)
                        if isinstance(item, tuple) and item[0] == "__result__":
                            pp_result = item[1]
                        else:
                            yield _sse_encode({
                                "type": "video_progress",
                                "video_index": i,
                                "step": item["step"],
                                "message": item["message"],
                            })
                    await asyncio.sleep(0.5)
                    # 发送心跳保持连接活跃
                    yield _sse_encode({
                        "type": "video_progress",
                        "video_index": i,
                        "step": 0,
                        "message": "处理中...",
                    })

                # 处理剩余队列
                while progress_queue:
                    item = progress_queue.pop(0)
                    if isinstance(item, tuple) and item[0] == "__result__":
                        pp_result = item[1]
                    else:
                        yield _sse_encode({
                            "type": "video_progress",
                            "video_index": i,
                            "step": item["step"],
                            "message": item["message"],
                        })

                if processing_error:
                    exc = processing_error[0]
                    # 单视频失败：持久化失败前已完成结果（幂等去重支持重试），
                    # 记录失败并继续处理下一个视频，不再中止整批。
                    _persist_batch_results(output_dir, all_processed, partial=True)
                    message = f"处理视频失败: {exc}"
                    failures.append({
                        "video_index": i,
                        "video_name": vp.stem,
                        "message": message,
                    })
                    yield _sse_encode({
                        "type": "video_failed",
                        "video_index": i,
                        "video_name": vp.stem,
                        "message": message,
                    })
                    continue

                if pp_result is None:
                    _persist_batch_results(output_dir, all_processed, partial=True)
                    message = "处理视频返回空结果"
                    failures.append({
                        "video_index": i,
                        "video_name": vp.stem,
                        "message": message,
                    })
                    yield _sse_encode({
                        "type": "video_failed",
                        "video_index": i,
                        "video_name": vp.stem,
                        "message": message,
                    })
                    continue

                processed, video_stem = pp_result
                cards_count = len(processed)

                # 为每个处理结果添加 video_stem 字段（用于独立模式分组）
                for p in processed:
                    p["video_stem"] = vp.stem

                yield _sse_encode({
                    "type": "video_done",
                    "video_index": i,
                    "video_name": vp.stem,
                    "cards": cards_count,
                })

                all_processed.extend(processed)
                total_cards += cards_count
                successes += 1

        except Exception as e:
            import traceback
            traceback.print_exc()
            # 持久化已完成视频的结果，支持重试时跳过它们（可恢复批处理）
            _persist_batch_results(output_dir, all_processed, partial=True)
            yield _sse_encode({"type": "error", "message": str(e)})
            # 即使出错也必须发送 complete 事件，否则前端 SSE 流会异常关闭
            yield _sse_encode({
                "type": "complete",
                "videos_processed": 0,
                "total_cards": 0,
                "error": True,
            })
            return

        # 记录已学单词并合并结果到 manifest（供 generate_apkg 使用）
        # 有失败时标记 partial，供前端与打包结果提示客户「牌组不完整」
        _persist_batch_results(output_dir, all_processed, partial=bool(failures))

        yield _sse_encode({
            "type": "complete",
            "videos_processed": successes,
            "total_cards": total_cards,
            "successes": successes,
            "failures": failures,
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
