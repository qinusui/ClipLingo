"""ASR/Whisper 转录封装 — 子进程 + pipe + 进度 store + 清理"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
import threading
import time as _time
import traceback as _traceback
from pathlib import Path

logger = None  # set by caller via logging.getLogger(__name__)

# ── Private constants (no global leakage) ──

_MAX_WHISPER_SECONDS = 1800  # 30-minute timeout

# Project root for subprocess sys.path injection
if getattr(sys, 'frozen', False):
    _PROJECT_ROOT = sys._MEIPASS
else:
    _PROJECT_ROOT = str(Path(__file__).parent.parent.parent)


def _get_bin_path(tool_name: str) -> str:
    """Get ffmpeg/ffprobe path, compatible with frozen and dev environments."""
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
    return tool_name


# ── Subprocess target ──

_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}


def _asr_subprocess(video_path: str, srt_path: str, asr_engine: str, model_name: str,
                    language: str, result_path: str, progress_pipe):
    """Run ASR transcription in an isolated child process; report progress via Pipe."""
    _sys = sys
    _sys.path.append(_PROJECT_ROOT)

    # Ensure child can find ctranslate2/onnxruntime native DLLs
    if getattr(_sys, 'frozen', False):
        try:
            _os = os
            _os.add_dll_directory(_sys._MEIPASS)
            _os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        except Exception:
            pass

    try:
        from core.asr import create_engine
        from core.whisper_transcribe import save_as_srt
        from core.media_cut import get_video_duration

        try:
            duration_sec = get_video_duration(video_path)
        except Exception:
            duration_sec = 0.0

        progress_pipe.send({"step": "loading", "message": f"初始化 {asr_engine} 引擎..."})

        if asr_engine == "faster_whisper":
            from core.whisper_manager import load_model

            def _download_progress(msg: str):
                progress_pipe.send({"step": "loading", "message": msg})

            model = load_model(model_name, progress_callback=_download_progress)
            if model is None:
                raise RuntimeError("Whisper 未安装，请先安装 Whisper")

            progress_pipe.send({"step": "transcribing", "message": "转录中...", "duration_sec": duration_sec})

            segments_iter, info = model.transcribe(
                video_path, language=language, word_timestamps=True, vad_filter=True,
            )

            segments = []
            for seg in segments_iter:
                text = seg.text.strip()
                if text:
                    segments.append({"start": seg.start, "end": seg.end, "text": text})
                    progress = min(seg.end / duration_sec, 1.0) if duration_sec > 0 else 0.0
                    progress_pipe.send({
                        "step": "transcribing",
                        "progress": progress,
                        "transcribed_sec": seg.end,
                        "duration_sec": duration_sec,
                        "text": text,
                    })
        else:
            engine = create_engine(asr_engine)

            def _progress(frac: float, msg: str):
                transcribed = frac * duration_sec if duration_sec > 0 else 0.0
                progress_pipe.send({
                    "step": "transcribing",
                    "progress": frac,
                    "transcribed_sec": transcribed,
                    "duration_sec": duration_sec,
                    "message": msg,
                })

            segments = engine.transcribe(video_path, language, progress_callback=_progress)

        save_as_srt(segments, srt_path)
        progress_pipe.send({"step": "done", "segment_count": len(segments)})

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump({"segment_count": len(segments)}, f)

    except Exception as e:
        progress_pipe.send({
            "step": "error",
            "error": str(e),
            "traceback": _traceback.format_exc(),
        })
        raise


# ── Public interface ──


def run_transcribe(
    task_id: str,
    video_path_str: str,
    srt_path_str: str,
    asr_engine: str,
    model_name: str,
    language: str | None,
    min_duration: float,
    store: dict,
    lock: threading.Lock,
) -> None:
    """
    Launch a background transcription task (runs in caller's thread).

    Manages the subprocess lifecycle, progress pipe, timeout watchdog,
    SRT parsing, and result writing into the shared store.
    """
    result_json_path = str(Path(video_path_str).with_suffix(".result.json"))
    proc = None
    _subprocess_error = None

    try:
        # Start ASR subprocess via pipe
        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)

        proc = multiprocessing.Process(
            target=_asr_subprocess,
            args=(video_path_str, srt_path_str, asr_engine, model_name,
                  language or "", result_json_path, child_conn),
            daemon=True,
        )
        proc.start()
        child_conn.close()

        with lock:
            store[task_id] = {"_proc": proc}

        transcribe_start = _time.time()
        timed_out = False
        cancelled = False

        while proc.is_alive():
            # Check cancellation
            with lock:
                if store.get(task_id, {}).get("_cancelled"):
                    cancelled = True
                    break

            # Timeout watchdog
            elapsed_total = _time.time() - transcribe_start
            if elapsed_total > _MAX_WHISPER_SECONDS:
                timed_out = True
                break

            if parent_conn.poll(1):
                try:
                    msg = parent_conn.recv()
                    step = msg.get("step")
                    if step == "loading":
                        _update_status(store, lock, task_id, "processing", 1, msg.get("message", "加载模型中..."))
                    elif step == "transcribing":
                        if "progress" in msg:
                            with lock:
                                s = store.get(task_id, {})
                                s["whisper_progress"] = {
                                    "progress": msg["progress"],
                                    "transcribed_sec": msg["transcribed_sec"],
                                    "duration_sec": msg["duration_sec"],
                                    "text": msg.get("text", ""),
                                }
                                store[task_id] = s
                        else:
                            _update_status(store, lock, task_id, "processing", 2, "转录中，请耐心等待...")
                    elif step == "error":
                        _subprocess_error = msg.get("error", "转录子进程异常退出")
                        break
                    elif step == "done":
                        break
                except (EOFError, OSError):
                    break
            else:
                elapsed = int(_time.time() - transcribe_start)
                mins, secs = elapsed // 60, elapsed % 60
                _update_status(store, lock, task_id, "processing", 2, f"转录中... 已用时 {mins}分{secs}秒")

        # Terminate subprocess on timeout/cancel
        if timed_out or cancelled:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
                if proc.is_alive():
                    proc.kill()
            reason = "转录超时（超过 30 分钟）" if timed_out else "转录已取消"
            raise RuntimeError(reason)

        proc.join(timeout=30)

        if _subprocess_error:
            raise RuntimeError(_subprocess_error)
        if proc.exitcode != 0:
            raise RuntimeError(f"转录子进程异常退出 (code={proc.exitcode})")

        # Parse generated SRT
        from core.parse_srt import parse_srt, filter_short_subtitles

        _update_status(store, lock, task_id, "processing", 3, "解析生成的字幕...")
        subtitles = parse_srt(srt_path_str)
        original_count = len(subtitles)
        subtitles = filter_short_subtitles(subtitles, min_duration)

        subtitle_items = [{"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec,
                           "text": s.text, "duration": s.duration} for s in subtitles]

        with lock:
            store[task_id] = {
                "status": "completed",
                "step": 4,
                "total_steps": 4,
                "message": f"转录完成，共 {len(subtitle_items)} 条字幕",
                "result": {
                    "subtitles": subtitle_items,
                    "total": original_count,
                    "filtered": len(subtitle_items),
                },
            }

    except Exception as e:
        from errors import translate_error, ErrorCode
        error_code, error_msg = translate_error(e)
        with lock:
            store[task_id] = {
                "status": "error",
                "step": 0,
                "total_steps": 4,
                "message": f"转录失败: {error_msg}",
                "error": error_msg,
                "error_code": error_code.value,
            }

    finally:
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
        with lock:
            s = store.get(task_id, {})
            s.pop("_proc", None)
            s.pop("_cancelled", None)
            store[task_id] = s
        # Cleanup temp files
        for p in (video_path_str, srt_path_str, result_json_path):
            Path(p).unlink(missing_ok=True)


def _update_status(store: dict, lock: threading.Lock, task_id: str,
                   status: str, step: int, message: str) -> None:
    """Helper to update store atomically."""
    with lock:
        current = store.get(task_id, {})
        current.update({"status": status, "step": step, "total_steps": 4, "message": message})
        store[task_id] = current
