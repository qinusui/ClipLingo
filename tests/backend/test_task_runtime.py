import json
import time
from pathlib import Path

import sys

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from services.task_runtime import TaskRuntime


def test_create_processing_task_sets_initial_state_and_persists_durable_subset(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")

    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=2,
        select_recommended_only=False,
        video_names_order=["a.mp4", "b.mp4"],
        created_at=123.0,
    )

    task = runtime.store["task-1"]
    assert task["status"] == "preparing"
    assert task["step"] == 0
    assert task["total_steps"] == 5
    assert task["message"] == "准备处理 2 个视频..."
    assert task["output_dir"] == "/tmp/output/task-1"
    assert task["video_names_order"] == ["a.mp4", "b.mp4"]

    data = json.loads(runtime.tasks_file.read_text(encoding="utf-8"))
    assert data["task-1"]["status"] == "preparing"
    assert data["task-1"]["output_dir"] == "/tmp/output/task-1"
    assert "message" not in data["task-1"]
    assert "result" not in data["task-1"]


def test_named_transitions_update_status_and_persist_only_durable_fields(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=True,
        video_names_order=["a.mp4"],
        created_at=time.time(),
    )

    runtime.report_progress(
        "task-1",
        status="processing",
        step=2,
        total_steps=5,
        message="处理中",
        details={"retained": 3},
    )
    assert runtime.store["task-1"]["status"] == "processing"
    assert runtime.store["task-1"]["details"] == {"retained": 3}

    runtime.await_styles(
        "task-1",
        step=3,
        total_steps=5,
        message="媒体处理完成",
        result={"cards": [{"sentence": "Hello"}]},
    )
    assert runtime.store["task-1"]["status"] == "awaiting_styles"
    assert runtime.store["task-1"]["result"]["cards"][0]["sentence"] == "Hello"

    data = json.loads(runtime.tasks_file.read_text(encoding="utf-8"))
    assert data["task-1"]["status"] == "awaiting_styles"
    assert "details" not in data["task-1"]
    assert "result" not in data["task-1"]

    runtime.complete(
        "task-1",
        step=5,
        message="完成",
        result={"success": True, "cards": []},
    )
    assert runtime.store["task-1"]["status"] == "completed"

    runtime.fail("task-1", message="失败", error="boom", error_code="INTERNAL_ERROR")
    assert runtime.store["task-1"]["status"] == "error"
    assert runtime.store["task-1"]["error"] == "boom"
    assert runtime.store["task-1"]["error_code"] == "INTERNAL_ERROR"


def test_cancel_helpers_are_safe_for_missing_tasks(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")

    assert runtime.set_cancelled("missing") is False
    assert runtime.is_cancelled("missing") is False

    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=False,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )
    assert runtime.set_cancelled("task-1") is True
    assert runtime.is_cancelled("task-1") is True


def test_progress_view_returns_visible_task_fields(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )

    runtime.report_progress(
        "task-1",
        status="processing",
        step=2,
        total_steps=5,
        message="处理中",
        details={"processed": 4},
    )

    view = runtime.progress_view("task-1")
    assert view == {
        "task_id": "task-1",
        "status": "processing",
        "step": 2,
        "total_steps": 5,
        "message": "处理中",
        "details": {"processed": 4},
        "error": None,
        "error_code": None,
    }


def test_progress_view_includes_result_for_terminal_or_waiting_states(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )

    runtime.await_styles(
        "task-1",
        step=3,
        total_steps=5,
        message="媒体处理完成",
        result={"cards_count": 2},
    )
    assert runtime.progress_view("task-1")["result"] == {"cards_count": 2}

    runtime.complete(
        "task-1",
        step=5,
        message="完成",
        result={"cards_count": 2, "apkg_url": "/output/task-1/a.apkg"},
    )
    assert runtime.progress_view("task-1")["result"]["apkg_url"] == "/output/task-1/a.apkg"


def test_progress_view_includes_error_info_and_handles_missing(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    assert runtime.progress_view("missing") is None

    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )
    runtime.fail("task-1", message="处理失败: boom", error="boom", error_code="INTERNAL_ERROR")

    view = runtime.progress_view("task-1")
    assert view["status"] == "error"
    assert view["error"] == "boom"
    assert view["error_code"] == "INTERNAL_ERROR"


def test_batch_query_helpers_use_upload_order_or_fallback_names(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=2,
        select_recommended_only=True,
        video_names_order=["b.mp4", "a.mp4"],
    )

    assert runtime.upload_order("task-1") == ["b.mp4", "a.mp4"]
    assert runtime.upload_index_by_video_name("task-1", ["a.mp4", "b.mp4"]) == {
        "b.mp4": 0,
        "a.mp4": 1,
    }
    assert runtime.select_recommended_only("task-1") is True

    runtime.create("legacy", {"status": "completed"})
    assert runtime.upload_order("missing") == []
    assert runtime.upload_index_by_video_name("legacy", ["a.mp4", "b.mp4"]) == {
        "a.mp4": 0,
        "b.mp4": 1,
    }
    assert runtime.select_recommended_only("legacy") is False


def test_remaining_video_names_uses_upload_order_and_completed_stems(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=3,
        select_recommended_only=False,
        video_names_order=["first_video.mp4", "v2.mp4", "v3.mp4"],
    )

    remaining = runtime.remaining_video_names("task-1", {"first_video"})
    assert remaining == ["v2.mp4", "v3.mp4"]

    assert runtime.remaining_video_names("missing", {"first_video"}) == []


def test_packing_output_dir_requires_awaiting_styles(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )

    assert runtime.packing_output_dir("missing") is None
    assert runtime.packing_output_dir("task-1") is None

    runtime.await_styles(
        "task-1",
        step=3,
        total_steps=5,
        message="媒体处理完成",
        result={"cards_count": 1},
    )
    assert runtime.packing_output_dir("task-1") == "/tmp/output/task-1"


def test_output_dir_and_completed_result_accessors(tmp_path):
    runtime = TaskRuntime(tmp_path / "tasks.json")
    runtime.create_processing_task(
        "task-1",
        output_dir="/tmp/output/task-1",
        merge=True,
        total_videos=1,
        select_recommended_only=False,
        video_names_order=["a.mp4"],
    )

    assert runtime.output_dir("task-1") == "/tmp/output/task-1"
    assert runtime.output_dir("missing") is None
    assert runtime.completed_result("task-1") is None

    runtime.complete(
        "task-1",
        step=5,
        message="完成",
        result={"cards": [], "video_name": "a.mp4"},
    )
    assert runtime.completed_result("task-1") == {"cards": [], "video_name": "a.mp4"}
