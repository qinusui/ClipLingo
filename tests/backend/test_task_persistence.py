"""
C3 - task_store 持久化 / TTL 测试

验证：
- _durable_task_view 只提取耐久子集，排除大块 result/cards 与高频心跳字段；
- _flush_tasks + _load_tasks 在 TTL 内可往返恢复任务；
- 超过 TTL 的任务在启动加载时被丢弃；
- 落盘文件中不含 result/cards 等大块数据；
- 缺失/损坏的 tasks.json 不致崩溃。
"""

import json
import sys
import time
import importlib
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

process = importlib.import_module("api.process")


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """隔离 TASKS_FILE 与 task_store，避免污染真实 APPDATA。"""
    tasks_file = tmp_path / "tasks.json"
    monkeypatch.setattr(process, "TASKS_FILE", tasks_file)
    saved = dict(process.task_store)
    process.task_store.clear()
    try:
        yield tasks_file
    finally:
        process.task_store.clear()
        process.task_store.update(saved)


def _make_task(created_at=None):
    return {
        "status": "awaiting_styles",
        "step": 3,
        "total_steps": 5,
        "message": "媒体处理完成，请选择样式",
        "details": {"foo": "bar"},
        "result": {"cards": [{"sentence": "x" * 1000}], "cards_count": 1},
        "error": None,
        "error_code": None,
        "output_dir": "/tmp/output/abc",
        "merge": True,
        "total_videos": 2,
        "select_recommended_only": False,
        "video_names_order": ["a.mp4", "b.mp4"],
        "created_at": created_at if created_at is not None else time.time(),
    }


def test_durable_view_excludes_large_and_ephemeral_fields():
    view = process._durable_task_view(_make_task())
    # 耐久字段保留
    assert view["status"] == "awaiting_styles"
    assert view["output_dir"] == "/tmp/output/abc"
    assert view["merge"] is True
    assert view["video_names_order"] == ["a.mp4", "b.mp4"]
    assert "created_at" in view
    # 大块 / 高频心跳字段排除
    assert "result" not in view
    assert "message" not in view
    assert "details" not in view
    assert "step" not in view


def test_flush_and_load_roundtrip(isolated_store):
    tasks_file = isolated_store
    with process.task_store_lock:
        process.task_store["t1"] = _make_task()
        process._flush_tasks()

    assert tasks_file.exists()
    # 落盘文件不含大块卡片数据
    raw = tasks_file.read_text(encoding="utf-8")
    assert "cards" not in raw
    assert "x" * 1000 not in raw

    # 清空内存后从磁盘恢复
    process.task_store.clear()
    process._load_tasks()
    assert "t1" in process.task_store
    assert process.task_store["t1"]["output_dir"] == "/tmp/output/abc"
    assert process.task_store["t1"]["video_names_order"] == ["a.mp4", "b.mp4"]


def test_load_drops_expired_tasks(isolated_store):
    old = time.time() - (process.TASK_TTL_SECONDS + 60)
    fresh = time.time()
    with process.task_store_lock:
        process.task_store["old"] = _make_task(created_at=old)
        process.task_store["new"] = _make_task(created_at=fresh)
        process._flush_tasks()

    process.task_store.clear()
    process._load_tasks()
    assert "old" not in process.task_store
    assert "new" in process.task_store


def test_load_missing_file_is_noop(isolated_store):
    # 文件不存在时不报错、不写入
    process.task_store.clear()
    process._load_tasks()
    assert process.task_store == {}


def test_load_corrupt_file_does_not_crash(isolated_store):
    tasks_file = isolated_store
    tasks_file.write_text("{ not valid json", encoding="utf-8")
    process.task_store.clear()
    # 不应抛异常
    process._load_tasks()
    assert process.task_store == {}


def test_flush_writes_durable_subset_for_all_tasks(isolated_store):
    tasks_file = isolated_store
    with process.task_store_lock:
        process.task_store["t1"] = _make_task()
        process.task_store["t2"] = _make_task()
        process._flush_tasks()

    data = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"t1", "t2"}
    for entry in data.values():
        assert "result" not in entry
        assert "output_dir" in entry
