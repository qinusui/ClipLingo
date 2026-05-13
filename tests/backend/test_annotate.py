"""
测试后台预热注释 API

覆盖:
- 预热触发（正常 + 无 task_id）
- 缓存查询（get_cached_items）
- 预热进度查询
- 边界情况
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from backend.main import app
# 必须从 api.annotate 导入（与端点内 import 路径一致），否则会得到不同的模块实例
from api.annotate import _preheat_cache, _cache_lock, get_cached_items
from api.subtitles import _inject_context

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cache():
    """每个测试前清空预热缓存"""
    _preheat_cache.clear()
    yield
    _preheat_cache.clear()


class TestPreheatTrigger:
    """预热触发端点测试"""

    def test_preheat_no_task_id(self):
        """无 task_id 时跳过预热"""
        resp = client.post("/api/annotate/preheat", json={
            "task_id": "",
            "subtitles": [{"index": 0, "start_sec": 1.0, "end_sec": 2.0, "text": "Hello"}],
            "purpose": "grammar",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"

    def test_preheat_without_api_key(self):
        """无 API Key 时不报错，后台静默跳过"""
        resp = client.post("/api/annotate/preheat", json={
            "task_id": "test-task-1",
            "subtitles": [{"index": 0, "start_sec": 1.0, "end_sec": 2.0, "text": "Hello"}],
            "purpose": "grammar",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "preheating"
        # 没有 API key，后台任务会静默跳过

    def test_preheat_init_cache_slots(self):
        """触发预热后初始化缓存槽位（TestClient 同步执行后台任务，可能已完成）"""
        resp = client.post("/api/annotate/preheat", json={
            "task_id": "test-task-2",
            "subtitles": [
                {"index": 1, "start_sec": 1.0, "end_sec": 2.0, "text": "Hello"},
                {"index": 2, "start_sec": 3.0, "end_sec": 4.0, "text": "World"},
            ],
            "purpose": "grammar",
        })
        assert resp.status_code == 200
        # 缓存槽位应存在（pending 或 done，取决于 API key 是否可用）
        s1 = _preheat_cache.get("test-task-2:grammar:1", {}).get("status")
        s2 = _preheat_cache.get("test-task-2:grammar:2", {}).get("status")
        assert s1 in ("pending", "done"), f"Unexpected status: {s1}"
        assert s2 in ("pending", "done"), f"Unexpected status: {s2}"

    def test_preheat_duplicate_does_not_clear_cache(self):
        """重复触发预热：已存在的缓存保持（仅跳过槽位初始化），但后台任务会写入新结果"""
        _preheat_cache["test-task-3:grammar:1"] = {"status": "done", "data": {"translation": "你好"}}

        resp = client.post("/api/annotate/preheat", json={
            "task_id": "test-task-3",
            "subtitles": [
                {"index": 1, "start_sec": 1.0, "end_sec": 2.0, "text": "Hello"},
            ],
            "purpose": "grammar",
        })
        assert resp.status_code == 200
        # 缓存条目存在（后台任务同步执行后会更新为实际结果）
        assert "test-task-3:grammar:1" in _preheat_cache
        assert _preheat_cache["test-task-3:grammar:1"]["status"] == "done"


class TestPreheatStatus:
    """预热进度查询测试"""

    def test_status_empty(self):
        """无缓存时返回零"""
        resp = client.get("/api/annotate/preheat/nonexistent/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"done": 0, "failed": 0, "total": 0}

    def test_status_counts(self):
        """正确统计 done/failed/total"""
        _preheat_cache["t1:grammar:0"] = {"status": "done", "data": {}}
        _preheat_cache["t1:grammar:1"] = {"status": "done", "data": {}}
        _preheat_cache["t1:grammar:2"] = {"status": "failed", "data": None}
        _preheat_cache["t1:grammar:3"] = {"status": "pending", "data": None}

        resp = client.get("/api/annotate/preheat/t1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["done"] == 2
        assert data["failed"] == 1
        assert data["total"] == 4

    def test_status_isolated_by_task(self):
        """不同 task_id 的缓存互不影响"""
        _preheat_cache["t1:grammar:0"] = {"status": "done", "data": {}}
        _preheat_cache["t2:grammar:0"] = {"status": "done", "data": {}}
        _preheat_cache["t2:grammar:1"] = {"status": "done", "data": {}}

        resp = client.get("/api/annotate/preheat/t1/status")
        assert resp.json()["total"] == 1

        resp = client.get("/api/annotate/preheat/t2/status")
        assert resp.json()["total"] == 2


class TestGetCachedItems:
    """get_cached_items 函数测试"""

    def test_returns_only_done(self):
        """只返回 status=done 的条目"""
        _preheat_cache["t1:grammar:0"] = {"status": "done", "data": {"translation": "你好"}}
        _preheat_cache["t1:grammar:1"] = {"status": "failed", "data": None}
        _preheat_cache["t1:grammar:2"] = {"status": "pending", "data": None}

        result = get_cached_items("t1", "grammar")
        assert len(result) == 1
        assert result[0] == {"translation": "你好"}

    def test_keyed_by_purpose(self):
        """不同 purpose 的缓存隔离"""
        _preheat_cache["t1:grammar:0"] = {"status": "done", "data": {"notes": "grammar note"}}
        _preheat_cache["t1:vocab:0"] = {"status": "done", "data": {"word": "hello"}}

        grammar = get_cached_items("t1", "grammar")
        vocab = get_cached_items("t1", "vocab")
        assert grammar[0] == {"notes": "grammar note"}
        assert vocab[0] == {"word": "hello"}

    def test_empty_for_missing_task(self):
        """不存在的 task_id 返回空"""
        assert get_cached_items("no-such-task", "grammar") == {}


class TestInjectContext:
    """_inject_context 测试"""

    def test_single_item_no_context(self):
        """单条字幕无前后文"""
        items = [{"index": 0, "text": "Hello"}]
        result = _inject_context(items)
        assert len(result) == 1
        assert "prev_text" not in result[0]
        assert "next_text" not in result[0]

    def test_first_item_has_only_next(self):
        """第一条只有后继"""
        items = [
            {"index": 0, "text": "Hello"},
            {"index": 1, "text": "World"},
        ]
        result = _inject_context(items)
        assert "prev_text" not in result[0]
        assert result[0]["next_text"] == "World"
        assert result[1]["prev_text"] == "Hello"
        assert "next_text" not in result[1]

    def test_middle_item_has_both(self):
        """中间条目有前后文"""
        items = [
            {"index": 0, "text": "A"},
            {"index": 1, "text": "B"},
            {"index": 2, "text": "C"},
        ]
        result = _inject_context(items)
        assert result[1]["prev_text"] == "A"
        assert result[1]["next_text"] == "C"
        assert result[1]["text"] == "B"

    def test_preserves_original_fields(self):
        """注入上下文不修改已有字段"""
        items = [{"index": 5, "text": "Hi", "start_sec": 1.0}]
        result = _inject_context(items)
        assert result[0]["index"] == 5
        assert result[0]["start_sec"] == 1.0

    def test_empty_list(self):
        """空列表不报错"""
        assert _inject_context([]) == []
