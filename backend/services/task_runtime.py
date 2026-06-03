"""Task runtime state and persistence.

The Task runtime owns the in-memory task store, durable persistence, and
state mutation helpers used by process endpoints.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TASK_TTL_SECONDS = 24 * 3600

_DURABLE_TASK_FIELDS = (
    "status",
    "output_dir",
    "merge",
    "total_videos",
    "select_recommended_only",
    "video_names_order",
    "error",
    "error_code",
    "created_at",
)


class TaskRuntime:
    """Owns Task state transitions and durable persistence."""

    def __init__(self, tasks_file: Path):
        self.tasks_file = tasks_file
        self.store: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def durable_view(self, task: dict[str, Any]) -> dict[str, Any]:
        return {k: task[k] for k in _DURABLE_TASK_FIELDS if k in task}

    def flush_locked(self) -> None:
        """Persist the durable subset.

        Caller must hold ``self.lock``.
        """
        try:
            snapshot = {tid: self.durable_view(t) for tid, t in self.store.items()}
            self.tasks_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.tasks_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.tasks_file)
        except Exception as e:
            logger.warning("持久化 tasks.json 失败: %s", e)

    def load(self) -> None:
        if not self.tasks_file.exists():
            return
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("加载 tasks.json 失败，已忽略: %s", e)
            return
        if not isinstance(data, dict):
            return

        now = time.time()
        with self.lock:
            for tid, task in data.items():
                if not isinstance(task, dict):
                    continue
                created = task.get("created_at", now)
                if now - created > TASK_TTL_SECONDS:
                    continue
                self.store[tid] = task
            self.flush_locked()

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.store.get(task_id)

    def create(self, task_id: str, task: dict[str, Any], *, persist: bool = True) -> None:
        with self.lock:
            self.store[task_id] = task
            if persist:
                self.flush_locked()

    def create_processing_task(
        self,
        task_id: str,
        *,
        output_dir: str,
        merge: bool,
        total_videos: int,
        select_recommended_only: bool,
        video_names_order: list[str],
        created_at: float | None = None,
    ) -> None:
        self.create(task_id, {
            "status": "preparing",
            "step": 0,
            "total_steps": 5,
            "message": f"准备处理 {total_videos} 个视频...",
            "details": None,
            "result": None,
            "error": None,
            "error_code": None,
            "output_dir": output_dir,
            "merge": merge,
            "total_videos": total_videos,
            "select_recommended_only": select_recommended_only,
            "video_names_order": list(video_names_order),
            "created_at": created_at if created_at is not None else time.time(),
        })

    def update(self, task_id: str, values: dict[str, Any], *, persist: bool = False) -> None:
        with self.lock:
            self.store[task_id].update(values)
            if persist:
                self.flush_locked()

    def start_processing(self, task_id: str, message: str = "开始处理...") -> None:
        self.update(task_id, {
            "status": "processing",
            "message": message,
        })

    def report_progress(
        self,
        task_id: str,
        *,
        status: str,
        step: int,
        total_steps: int,
        message: str,
        details: Any = None,
    ) -> None:
        self.update(task_id, {
            "status": status,
            "step": step,
            "total_steps": total_steps,
            "message": message,
            "details": details,
        })

    def await_styles(self, task_id: str, *, step: int, total_steps: int, message: str, result: dict[str, Any]) -> None:
        self.update(task_id, {
            "status": "awaiting_styles",
            "step": step,
            "total_steps": total_steps,
            "message": message,
            "result": result,
        }, persist=True)

    def complete(
        self,
        task_id: str,
        *,
        step: int,
        message: str,
        result: dict[str, Any],
        total_steps: int | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": "completed",
            "step": step,
            "message": message,
            "result": result,
        }
        if total_steps is not None:
            values["total_steps"] = total_steps
        self.update(task_id, values, persist=True)

    def fail(self, task_id: str, *, message: str, error: str, error_code: str) -> None:
        self.update(task_id, {
            "status": "error",
            "message": message,
            "error": error,
            "error_code": error_code,
        }, persist=True)

    def progress_view(self, task_id: str) -> dict[str, Any] | None:
        task = self.get(task_id)
        if not task:
            return None

        response = {
            "task_id": task_id,
            "status": task["status"],
            "step": task["step"],
            "total_steps": task["total_steps"],
            "message": task["message"],
            "details": task["details"],
            "error": task.get("error"),
            "error_code": task.get("error_code"),
        }

        if task["status"] in ("completed", "awaiting_styles", "packing") and task.get("result"):
            response["result"] = task["result"]
        elif task["status"] == "error":
            response["error"] = task.get("error")
            response["error_code"] = task.get("error_code")

        return response

    def exists(self, task_id: str) -> bool:
        with self.lock:
            return task_id in self.store

    def upload_order(self, task_id: str) -> list[str]:
        task = self.get(task_id)
        if not task:
            return []
        return list(task.get("video_names_order") or [])

    def upload_index_by_video_name(self, task_id: str, fallback_names: list[str]) -> dict[str, int]:
        names = self.upload_order(task_id) or list(fallback_names)
        return {name: i for i, name in enumerate(names)}

    def select_recommended_only(self, task_id: str, default: bool = False) -> bool:
        task = self.get(task_id)
        if not task:
            return default
        return bool(task.get("select_recommended_only", default))

    def remaining_video_names(self, task_id: str, completed_stems: set[str]) -> list[str]:
        return [
            name for name in self.upload_order(task_id)
            if Path(name).stem not in completed_stems
        ]

    def output_dir(self, task_id: str) -> str | None:
        task = self.get(task_id)
        if not task:
            return None
        return task.get("output_dir")

    def packing_output_dir(self, task_id: str) -> str | None:
        task = self.get(task_id)
        if not task or task.get("status") != "awaiting_styles":
            return None
        return task.get("output_dir")

    def completed_result(self, task_id: str) -> dict[str, Any] | None:
        task = self.get(task_id)
        if not task or task.get("status") != "completed":
            return None
        return task.get("result")

    def remove(self, task_id: str, *, persist: bool = True) -> None:
        with self.lock:
            self.store.pop(task_id, None)
            if persist:
                self.flush_locked()

    def set_cancelled(self, task_id: str) -> bool:
        with self.lock:
            task = self.store.get(task_id)
            if not task:
                return False
            task["_cancelled"] = True
            return True

    def is_cancelled(self, task_id: str) -> bool:
        with self.lock:
            return bool(self.store.get(task_id, {}).get("_cancelled"))
