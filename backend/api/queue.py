"""
批量队列处理 API
多个视频串行处理，无需人工介入每个视频
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import threading
import uuid
import shutil
import zipfile
import tempfile
import sys

if getattr(sys, 'frozen', False):
    _ROOT = Path(sys._MEIPASS)
    _INSTALL_DIR = Path(sys.executable).parent
else:
    _ROOT = Path(__file__).parent.parent
    _INSTALL_DIR = _ROOT.parent

sys.path.insert(0, str(_ROOT))

from main import run as process_cards
from errors import translate_error

router = APIRouter()


class TaskStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueueTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str = ""
    video_path: str = ""
    subtitle_path: str = ""
    video_name: str = ""
    output_dir: str = ""
    params: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.WAITING
    step: int = 0
    message: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None


# 模块级队列
_queue: list[QueueTask] = []
_queue_lock = threading.Lock()
_executor_thread: Optional[threading.Thread] = None
_executor_running = False

# 进度回调映射（task_id -> QueueTask），供 process_cards 回调写入
_task_map: dict[str, QueueTask] = {}


def _next_waiting() -> Optional[QueueTask]:
    with _queue_lock:
        for t in _queue:
            if t.status == TaskStatus.WAITING:
                return t
    return None


def _make_progress_callback(task: QueueTask):
    """为 QueueTask 生成 progress_callback"""
    def callback(step, total_steps, message, details=None):
        task.step = step
        task.message = message
    return callback


def _run_single_task(task: QueueTask):
    """执行单个任务（同步）"""
    task.status = TaskStatus.RUNNING
    task.message = "开始处理..."

    try:
        result = process_cards(
            video_path=task.video_path,
            subtitle_path=task.subtitle_path or None,
            output_dir=task.output_dir,
            progress_callback=_make_progress_callback(task),
            **task.params,
        )

        apkg_name = Path(result["apkg_path"]).name
        task.result = {
            "success": True,
            "task_id": task.id,
            "video_name": task.video_name,
            "cards_count": result["cards_count"],
            "apkg_path": apkg_name,
            "apkg_url": f"/output/{task.id}/{apkg_name}",
            "cards": [
                {
                    "sentence": p.get("text", ""),
                    "translation": p.get("translation", ""),
                    "notes": p.get("notes", ""),
                    "word": p.get("word", ""),
                    "definition": p.get("definition", ""),
                    "start_sec": p.get("start_sec", 0),
                    "end_sec": p.get("end_sec", 0),
                    "audio_path": f"/output/{task.id}/audio/{Path(p.get('audio_path', '')).name}" if p.get("audio_path") else None,
                    "screenshot_path": f"/output/{task.id}/screenshots/{Path(p.get('screenshot_path', '')).name}" if p.get("screenshot_path") else None,
                }
                for p in result.get("processed", [])
            ],
        }
        task.status = TaskStatus.DONE
        task.step = 5
        task.message = f"完成，{result['cards_count']} 张卡片"

        # 记录已学单词
        try:
            from services.progress import mark_words_learned
            words = [
                {"word": p.get("word", ""), "definition": p.get("definition", "")}
                for p in result.get("processed", [])
                if p.get("word")
            ]
            if words:
                mark_words_learned(words, source_video=task.video_name)
        except Exception:
            pass

    except Exception as e:
        _, error_msg = translate_error(e)
        task.status = TaskStatus.FAILED
        task.error = error_msg
        task.message = f"失败: {error_msg}"


def _executor_loop():
    """串行执行器：逐个处理队列中的任务"""
    global _executor_running
    _executor_running = True

    while True:
        task = _next_waiting()
        if not task:
            break

        # 检查是否被取消
        if task.status == TaskStatus.CANCELLED:
            continue

        _run_single_task(task)

    _executor_running = False


def _ensure_executor():
    """确保执行器线程在运行"""
    global _executor_thread
    if _executor_running and _executor_thread and _executor_thread.is_alive():
        return
    _executor_thread = threading.Thread(target=_executor_loop, daemon=True)
    _executor_thread.start()


def _get_base_output() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "output"
    return _ROOT.parent / "output"


@router.post("/add")
async def add_to_queue(
    videos: list[UploadFile] = File(...),
    subtitles: list[UploadFile] = File(...),
    api_key: Optional[str] = Form(None),
    api_base: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
    min_duration: float = Form(1.0),
    language: Optional[str] = Form(None),
    whisper_model: str = Form("base"),
    force_transcribe: bool = Form(False),
    padding_start_ms: int = Form(200),
    padding_end_ms: int = Form(200),
    card_styles: Optional[str] = Form(None),
    theme: str = Form("default"),
):
    """批量添加任务到队列"""
    if not videos:
        raise HTTPException(status_code=400, detail="至少需要一个视频文件")
    if len(subtitles) != len(videos):
        raise HTTPException(status_code=400, detail="字幕文件数量必须与视频文件数量一致")

    batch_id = str(uuid.uuid4())[:8]
    base_output = _get_base_output()

    # 解析参数
    params = {}
    if api_key:
        params["api_key"] = api_key
    if api_base:
        params["api_base"] = api_base
    if model_name:
        params["model_name"] = model_name
    params["min_duration"] = min_duration
    if language:
        params["language"] = language
    params["whisper_model"] = whisper_model
    params["force_transcribe"] = force_transcribe
    params["padding_start_ms"] = padding_start_ms
    params["padding_end_ms"] = padding_end_ms
    if card_styles:
        try:
            import json
            params["card_styles"] = json.loads(card_styles)
        except Exception:
            params["card_styles"] = [card_styles]
    params["theme"] = theme

    tasks_info = []

    with _queue_lock:
        for video, subtitle in zip(videos, subtitles):
            task_id = str(uuid.uuid4())
            task_dir = Path(tempfile.mkdtemp(prefix="cliplingo_q_"))
            output_dir = str(base_output / task_id)

            # 保存文件
            v_path = task_dir / video.filename
            s_path = task_dir / subtitle.filename
            with open(v_path, "wb") as f:
                shutil.copyfileobj(video.file, f)
            with open(s_path, "wb") as f:
                shutil.copyfileobj(subtitle.file, f)

            task = QueueTask(
                id=task_id,
                batch_id=batch_id,
                video_path=str(v_path),
                subtitle_path=str(s_path),
                video_name=video.filename,
                output_dir=output_dir,
                params=params.copy(),
            )
            _queue.append(task)
            _task_map[task_id] = task

            tasks_info.append({
                "task_id": task_id,
                "video_name": video.filename,
                "status": task.status.value,
            })

    # 启动执行器
    _ensure_executor()

    return {
        "batch_id": batch_id,
        "tasks": tasks_info,
        "total": len(tasks_info),
    }


@router.get("/status")
async def get_queue_status(batch_id: Optional[str] = None):
    """获取队列状态"""
    with _queue_lock:
        tasks = [t for t in _queue if not batch_id or t.batch_id == batch_id]

    task_list = []
    for t in tasks:
        item = {
            "task_id": t.id,
            "video_name": t.video_name,
            "status": t.status.value,
            "step": t.step,
            "message": t.message,
        }
        if t.result:
            item["result"] = t.result
        if t.error:
            item["error"] = t.error
        task_list.append(item)

    done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    cancelled = sum(1 for t in tasks if t.status == TaskStatus.CANCELLED)
    total = len(tasks)

    return {
        "batch_id": batch_id,
        "tasks": task_list,
        "total": total,
        "done": done,
        "failed": failed,
        "cancelled": cancelled,
        "running": _executor_running,
    }


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    """取消等待中的任务"""
    with _queue_lock:
        task = _task_map.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task.status != TaskStatus.WAITING:
            raise HTTPException(status_code=400, detail=f"任务状态为 {task.status.value}，无法取消")
        task.status = TaskStatus.CANCELLED
        task.message = "已取消"

    return {"task_id": task_id, "status": "cancelled"}


@router.get("/download-all")
async def download_all(batch_id: Optional[str] = None):
    """将所有已完成任务的 apkg 打包为 ZIP 下载"""
    with _queue_lock:
        tasks = [
            t for t in _queue
            if t.status == TaskStatus.DONE
            and t.result
            and (not batch_id or t.batch_id == batch_id)
        ]

    if not tasks:
        raise HTTPException(status_code=404, detail="没有已完成的任务")

    # 创建临时 ZIP
    zip_path = Path(tempfile.mktemp(suffix=".zip"))
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zf:
        for t in tasks:
            apkg_url = t.result.get("apkg_url", "")
            # 从 URL 反推文件路径
            apkg_file = Path(t.output_dir) / t.result.get("apkg_path", "")
            if apkg_file.exists():
                zf.write(str(apkg_file), t.result.get("apkg_path", apkg_file.name))

    return FileResponse(
        str(zip_path),
        filename="ClipLingo_Batch.zip",
        media_type="application/zip",
        background=None,
    )


@router.delete("/batch/{batch_id}")
async def cancel_batch(batch_id: str):
    """取消整个批次中所有等待中的任务"""
    cancelled = 0
    with _queue_lock:
        for t in _queue:
            if t.batch_id == batch_id and t.status == TaskStatus.WAITING:
                t.status = TaskStatus.CANCELLED
                t.message = "已取消"
                cancelled += 1

    return {"batch_id": batch_id, "cancelled": cancelled}
