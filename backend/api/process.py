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

from models.schemas import ProcessRequest, ProcessResult, ProcessedCard, ProcessProgress

# 导入现有模块
import sys
if getattr(sys, 'frozen', False):
    # PyInstaller 打包环境
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import run as process_cards, generate_apkg
from api.subtitles import _build_screening_prompt, _build_annotation_prompt

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

    # 保存所有上传的文件
    video_paths = []
    subtitle_paths = []
    video_names = []

    for i, video in enumerate(videos):
        v_path = task_dir / video.filename
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

            is_merge = result.get("apkg_path") is not None  # merge=True 返回 apkg_path
            if is_merge:
                apkg_filename = Path(result["apkg_path"]).name
                cards = _build_cards(result.get("processed", []))
                with task_store_lock:
                    task_store[task_id].update({
                        "status": "completed",
                        "step": 1,
                        "total_steps": 2,
                        "message": f"处理完成，生成了 {result['cards_count']} 张卡片",
                        "result": {
                            "success": True,
                            "message": f"处理完成，生成了 {result['cards_count']} 张卡片",
                            "task_id": task_id,
                            "cards_count": result["cards_count"],
                            "apkg_path": apkg_filename,
                            "apkg_url": f"/output/{task_id}/{apkg_filename}",
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
                        "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片",
                        "result": {
                            "success": True,
                            "message": f"处理完成，{len(all_results)} 个视频共 {result['total_cards']} 张卡片",
                            "task_id": task_id,
                            "merge": False,
                            "total_cards": result["total_cards"],
                            "videos": apkg_list,
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
