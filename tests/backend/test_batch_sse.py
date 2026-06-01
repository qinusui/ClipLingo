"""
集成测试：batch_process SSE 端点

使用 FastAPI TestClient 直接调用 /api/process/batch-process，
验证 SSE 事件流格式、manifest 持久化、错误路径和中断恢复。

测试内容：
1. SSE 错误路径：task 目录不存在、videos 目录不存在、无匹配视频
2. 成功批处理：manifest 合并模式写入验证
3. 成功批处理：manifest 独立模式写入验证
4. SSE 事件流格式：start → video_done → complete 顺序正确
5. 中途失败：第一个视频成功后一个失败，验证 error 事件和部分结果
6. 字幕映射：subtitle_files 正确匹配视频文件
"""
import json
import sys
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from backend.main import app
import api.process as process_module

client = TestClient(app)


def _parse_sse_events(response):
    """解析 SSE 流，返回所有事件的 (type, data) 列表"""
    events = []
    for line in response.iter_lines():
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            events.append(payload)
    return events


def _make_fake_task(tmp_path, task_id, video_names, merge=True):
    """
    在 tmp_path 下构建完整的 task 目录结构：

    tmp_path/
      temp/{task_id}/
        videos/
          video1.mp4
          video2.mp4
        video1.srt  (可选字幕)
      output/{task_id}/
        processed_cards.json
    """
    temp_dir = tmp_path / "temp"
    task_dir = temp_dir / task_id
    videos_dir = task_dir / "videos"
    videos_dir.mkdir(parents=True)

    for name in video_names:
        (videos_dir / name).write_bytes(b"fake video")

    output_dir = tmp_path / "output" / task_id
    output_dir.mkdir(parents=True)

    # Phase 1 创建的初始 manifest（第一个视频已完成）
    manifest = {
        "merge": merge,
        "processed": [
            {"index": i, "video_stem": "first_video", "text": f"Card {i}"}
            for i in range(1, 11)
        ],
    }
    if not merge:
        manifest["results"] = [
            {
                "video_name": "first_video",
                "cards_count": 10,
                "processed": manifest["processed"],
            }
        ]
        manifest["total_cards"] = 10
        manifest["processed"] = []

    manifest_path = output_dir / "processed_cards.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    return temp_dir, output_dir


@pytest.fixture
def patch_temp_dir(tmp_path):
    """将 TEMP_DIR 替换为 tmp_path/temp"""
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    original = process_module.TEMP_DIR
    process_module.TEMP_DIR = temp_dir
    yield temp_dir
    process_module.TEMP_DIR = original


@pytest.fixture(autouse=True)
def clear_task_store():
    """每个测试前清空 task_store"""
    process_module.task_store.clear()
    yield
    process_module.task_store.clear()


def _mock_process_video_to_media(result_cards, video_stem):
    """返回一个 mock，模拟 _process_video_to_media 成功返回"""
    def fake_fn(**kwargs):
        progress_cb = kwargs.get("progress_callback")
        if progress_cb:
            progress_cb(1, 5, "Whisper 转录中...")
            progress_cb(2, 5, "AI 筛选中...")
            progress_cb(3, 5, "AI 标注中...")
            progress_cb(4, 5, "媒体切割中...")
            progress_cb(5, 5, "完成")
        return result_cards, video_stem
    return fake_fn


# ─── SSE 错误路径测试 ─────────────────────────────────────────


class TestBatchProcessErrors:
    """批处理 SSE 端点的错误处理"""

    def test_error_task_dir_not_found(self, patch_temp_dir):
        """task_id 对应的目录不存在时返回 error 事件"""
        resp = client.post("/api/process/batch-process", json={
            "task_id": "nonexistent-task",
            "video_names": ["video1.mp4"],
            "subtitle_files": [""],
        })
        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "不存在" in events[0]["message"]

    def test_error_videos_dir_not_found(self, tmp_path, patch_temp_dir):
        """task 目录存在但 videos 子目录不存在时返回 error"""
        task_id = "test-no-videos"
        task_dir = patch_temp_dir / task_id
        task_dir.mkdir(parents=True)  # 不创建 videos 子目录

        resp = client.post("/api/process/batch-process", json={
            "task_id": task_id,
            "video_names": ["video1.mp4"],
            "subtitle_files": [""],
        })
        events = _parse_sse_events(resp)
        assert any(e["type"] == "error" and "视频文件目录" in e["message"] for e in events)

    def test_error_no_matching_videos(self, tmp_path, patch_temp_dir):
        """video_names 与目录中的文件不匹配时返回 error"""
        task_id = "test-no-match"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video1.mp4"])
        process_module.TEMP_DIR = temp_dir

        resp = client.post("/api/process/batch-process", json={
            "task_id": task_id,
            "video_names": ["nonexistent.mp4"],
            "subtitle_files": [""],
        })
        events = _parse_sse_events(resp)
        assert any(e["type"] == "error" and "没有需要" in e["message"] for e in events)


# ─── 成功批处理：Manifest 持久化 ─────────────────────────────────


class TestBatchManifestPersistence:
    """批处理完成后 manifest 正确写入（原始 Bug 修复验证）"""

    def test_merge_mode_appends_to_manifest(self, tmp_path):
        """合并模式下批处理结果追加到 processed 列表"""
        task_id = "test-merge"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["video2.mp4", "video3.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 模拟 _process_video_to_media 返回
        video2_cards = [
            {"index": 10001 + i, "text": f"V2 card {i}", "translation": f"翻译{i}",
             "audio_path": "", "screenshot_path": ""}
            for i in range(5)
        ]
        video3_cards = [
            {"index": 20001 + i, "text": f"V3 card {i}", "translation": f"翻译{i}",
             "audio_path": "", "screenshot_path": ""}
            for i in range(3)
        ]

        call_count = [0]
        def mock_process(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return video2_cards, "video2"
            return video3_cards, "video3"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4", "video3.mp4"],
                "subtitle_files": ["", ""],
            })

        events = _parse_sse_events(resp)

        # 验证 SSE 事件流
        types = [e["type"] for e in events]
        assert "start" in types
        assert "complete" in types
        complete_event = next(e for e in events if e["type"] == "complete")
        assert complete_event.get("error") is not True
        assert complete_event["videos_processed"] == 2
        assert complete_event["total_cards"] == 8

        # 核心验证：manifest 已持久化
        manifest_path = output_dir / "processed_cards.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # 原有 10 张 + 新增 8 张
        assert len(manifest["processed"]) == 18
        stems = {c.get("video_stem") for c in manifest["processed"]}
        assert "first_video" in stems
        assert "video2" in stems
        assert "video3" in stems

    def test_independent_mode_appends_to_results(self, tmp_path):
        """独立模式下批处理结果追加到 results 列表"""
        task_id = "test-independent"
        temp_dir, output_dir = _make_fake_task(
            tmp_path, task_id, ["video2.mp4", "video3.mp4"], merge=False
        )
        process_module.TEMP_DIR = temp_dir

        video2_cards = [
            {"index": 10001 + i, "text": f"V2 card {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(4)
        ]
        video3_cards = [
            {"index": 20001 + i, "text": f"V3 card {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(6)
        ]

        call_count = [0]
        def mock_process(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return video2_cards, "video2"
            return video3_cards, "video3"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4", "video3.mp4"],
                "subtitle_files": ["", ""],
            })

        events = _parse_sse_events(resp)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete.get("error") is not True

        # 核心验证：独立模式 manifest
        manifest_path = output_dir / "processed_cards.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(manifest["results"]) == 3  # first_video + video2 + video3
        assert manifest["total_cards"] == 20  # 10 + 4 + 6

        result_names = {r["video_name"] for r in manifest["results"]}
        assert result_names == {"first_video", "video2", "video3"}

    def test_manifest_write_preserves_existing_data(self, tmp_path):
        """批处理写入 manifest 时不破坏已有的自定义字段"""
        task_id = "test-preserve"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 给 manifest 加一个自定义字段
        manifest_path = output_dir / "processed_cards.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["custom_field"] = {"theme": "dark", "card_styles": ["basic"]}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        cards = [{"index": 10001, "text": "Card", "audio_path": "", "screenshot_path": ""}]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "video2")
        ):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                "subtitle_files": [""],
            })

        # 自定义字段保留
        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert final["custom_field"] == {"theme": "dark", "card_styles": ["basic"]}
        assert len(final["processed"]) == 11  # 10 + 1


class TestBatchIdempotency:
    """重跑 batch-process（apkg 生成前）不应重复卡片"""

    def test_merge_mode_rerun_no_duplicate(self, tmp_path):
        """合并模式：同一任务重跑 batch，manifest 卡片不翻倍"""
        task_id = "test-idem-merge"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 两次都返回同一批卡片（相同 index）
        cards = [
            {"index": 10001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(4)
        ]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "video2"),
        ):
            for _ in range(2):
                client.post("/api/process/batch-process", json={
                    "task_id": task_id,
                    "video_names": ["video2.mp4"],
                    "subtitle_files": [""],
                })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        # 10 原有 + 4 新增；重跑不应再加 4
        assert len(manifest["processed"]) == 14
        v2 = [c for c in manifest["processed"] if c.get("video_stem") == "video2"]
        assert len(v2) == 4

    def test_independent_mode_rerun_no_duplicate(self, tmp_path):
        """独立模式：同一任务重跑 batch，results 不重复追加同一视频"""
        task_id = "test-idem-indep"
        temp_dir, output_dir = _make_fake_task(
            tmp_path, task_id, ["video2.mp4"], merge=False
        )
        process_module.TEMP_DIR = temp_dir

        cards = [
            {"index": 10001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(4)
        ]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "video2"),
        ):
            for _ in range(2):
                client.post("/api/process/batch-process", json={
                    "task_id": task_id,
                    "video_names": ["video2.mp4"],
                    "subtitle_files": [""],
                })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        names = [r["video_name"] for r in manifest["results"]]
        # first_video + video2，重跑不应再追加第二个 video2
        assert names.count("video2") == 1
        assert manifest["total_cards"] == 14  # 10 + 4


# ─── SSE 事件流格式验证 ─────────────────────────────────────────


class TestSSEEventFormat:
    """SSE 事件流的格式和顺序验证"""

    def test_event_order_start_done_complete(self, tmp_path):
        """事件顺序：start → video_done (per video) → complete"""
        task_id = "test-order"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards = [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "video2")
        ):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                "subtitle_files": [""],
            })

        events = _parse_sse_events(resp)
        types = [e["type"] for e in events]

        # start 在最前
        assert types[0] == "start"
        # complete 在最后
        assert types[-1] == "complete"
        # 中间有 video_done
        assert "video_done" in types

        # 验证 start 事件格式
        start = events[0]
        assert start["total_videos"] == 1

        # 验证 video_done 事件格式
        video_done = next(e for e in events if e["type"] == "video_done")
        assert "video_name" in video_done
        assert "cards" in video_done
        assert video_done["cards"] == 1

    def test_heartbeat_events_during_processing(self, tmp_path):
        """处理期间有心跳事件（防止 SSE 超时断开）"""
        task_id = "test-heartbeat"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards = [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "video2")
        ):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                "subtitle_files": [""],
            })

        events = _parse_sse_events(resp)
        # video_progress 事件（心跳）应该存在
        progress_events = [e for e in events if e["type"] == "video_progress"]
        # 至少有 1 个进度事件（来自 progress_callback 或心跳）
        assert len(progress_events) >= 1

    def test_complete_event_has_total_cards(self, tmp_path):
        """complete 事件包含 videos_processed 和 total_cards"""
        task_id = "test-totals"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards = [
            {"index": i, "text": f"c{i}", "audio_path": "", "screenshot_path": ""}
            for i in range(7)
        ]

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=(cards, "v2")
        ):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        events = _parse_sse_events(resp)
        complete = next(e for e in events if e["type"] == "complete")
        assert complete["videos_processed"] == 2
        assert complete["total_cards"] == 14  # 7 * 2


# ─── 中途失败恢复 ──────────────────────────────────────────────


class TestBatchMidFailure:
    """批处理中途失败：错误事件和部分结果"""

    def test_second_video_fails_error_event(self, tmp_path):
        """第一个视频成功后第二个失败，应发送 error 和 error=True 的 complete"""
        task_id = "test-midfail"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards = [{"index": 1, "text": "ok", "audio_path": "", "screenshot_path": ""}]

        call_count = [0]
        def mock_process(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return cards, "v2"
            raise RuntimeError("AI API 连接超时")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        events = _parse_sse_events(resp)
        types = [e["type"] for e in events]

        # 第一个视频成功
        assert "video_done" in types

        # 第二个视频失败
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) >= 1
        assert "处理视频失败" in error_events[-1]["message"]

        # complete 事件带 error=True
        complete = next(e for e in events if e["type"] == "complete")
        assert complete.get("error") is True
        # 只处理了 1 个视频
        assert complete["videos_processed"] == 1

    def test_partial_manifest_after_failure(self, tmp_path):
        """中途失败时，失败前已完成视频的卡片仍写入 manifest（可恢复批处理）"""
        task_id = "test-partial"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards_v2 = [
            {"index": 10001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(5)
        ]

        call_count = [0]
        def mock_process(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return cards_v2, "v2"
            raise RuntimeError("网络错误")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        # 失败前已完成的 v2（5 张）应已落盘，配合幂等去重支持重试续跑
        manifest_path = output_dir / "processed_cards.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(manifest["processed"]) == 15  # 原有 10 + v2 的 5
        stems = {c.get("video_stem") for c in manifest["processed"]}
        assert "v2" in stems

    def test_retry_after_failure_resumes_without_duplicate(self, tmp_path):
        """失败后重试：已完成视频不重复，失败视频补齐（可恢复批处理）"""
        task_id = "test-resume"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        v2_cards = [
            {"index": 10001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(5)
        ]
        v3_cards = [
            {"index": 20001 + i, "text": f"V3 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(4)
        ]

        # 第一次：v2 成功、v3 失败
        run1 = [0]
        def mock_run1(**kwargs):
            idx = run1[0]; run1[0] += 1
            if idx == 0:
                return v2_cards, "v2"
            raise RuntimeError("网络错误")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_run1):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        assert len(manifest["processed"]) == 15  # 10 + v2(5)

        # 第二次重试：v2 再次成功（同 index）、v3 这次成功
        run2 = [0]
        def mock_run2(**kwargs):
            idx = run2[0]; run2[0] += 1
            if idx == 0:
                return v2_cards, "v2"
            return v3_cards, "v3"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_run2):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        # v2 去重不重复，v3 补齐：10 + 5 + 4 = 19
        assert len(manifest["processed"]) == 19
        v2_count = sum(1 for c in manifest["processed"] if c.get("video_stem") == "v2")
        assert v2_count == 5  # 未翻倍
        stems = {c.get("video_stem") for c in manifest["processed"]}
        assert {"v2", "v3"} <= stems

    def test_partial_flag_set_on_failure(self, tmp_path):
        """中途失败时 manifest 标记 partial=True，供打包结果提示客户牌组不完整"""
        task_id = "test-partial-flag"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        cards_v2 = [
            {"index": 30001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""}
            for i in range(3)
        ]

        call_count = [0]
        def mock_process(**kwargs):
            idx = call_count[0]; call_count[0] += 1
            if idx == 0:
                return cards_v2, "v2"
            raise RuntimeError("网络错误")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        assert manifest.get("partial") is True

    def test_partial_flag_set_when_first_video_fails(self, tmp_path):
        """首个批处理视频即失败（无新结果）时仍写入 partial=True"""
        task_id = "test-partial-first-fail"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4"])
        process_module.TEMP_DIR = temp_dir

        with patch.object(
            process_module, "_process_video_to_media",
            side_effect=RuntimeError("网络错误")
        ):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4"],
                "subtitle_files": [""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        assert manifest.get("partial") is True

    def test_partial_flag_cleared_on_full_success(self, tmp_path):
        """失败后重试全部成功，partial 标记清除为 False"""
        task_id = "test-partial-clear"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        v2_cards = [{"index": 40001 + i, "text": f"V2 {i}", "audio_path": "", "screenshot_path": ""} for i in range(3)]
        v3_cards = [{"index": 50001 + i, "text": f"V3 {i}", "audio_path": "", "screenshot_path": ""} for i in range(2)]

        run1 = [0]
        def mock_run1(**kwargs):
            idx = run1[0]; run1[0] += 1
            if idx == 0:
                return v2_cards, "v2"
            raise RuntimeError("网络错误")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_run1):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        assert manifest.get("partial") is True

        run2 = [0]
        def mock_run2(**kwargs):
            idx = run2[0]; run2[0] += 1
            return (v2_cards, "v2") if idx == 0 else (v3_cards, "v3")

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_run2):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        assert manifest.get("partial") is False

    def test_first_video_returns_none_error(self, tmp_path):
        """_process_video_to_media 返回 None 时触发 error"""
        task_id = "test-none-result"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["v2.mp4"])
        process_module.TEMP_DIR = temp_dir

        with patch.object(
            process_module, "_process_video_to_media",
            return_value=None
        ):
            resp = client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4"],
                "subtitle_files": [""],
            })

        events = _parse_sse_events(resp)
        error_events = [e for e in events if e["type"] == "error"]
        assert any("空结果" in e["message"] for e in error_events)

        complete = next(e for e in events if e["type"] == "complete")
        assert complete.get("error") is True


# ─── 字幕映射测试 ─────────────────────────────────────────────


class TestSubtitleMapping:
    """验证 subtitle_files 正确映射到对应视频"""

    def test_subtitle_file_found_and_passed(self, tmp_path):
        """subtitle_files 中指定的字幕文件能找到并传给 _process_video_to_media"""
        task_id = "test-sub-map"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 创建字幕文件
        task_dir = temp_dir / task_id
        (task_dir / "video2.srt").write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n",
            encoding="utf-8"
        )

        captured_args = []

        def mock_process(**kwargs):
            captured_args.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "video2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                "subtitle_files": ["video2.srt"],
            })

        assert len(captured_args) == 1
        assert captured_args[0]["subtitle_path"].endswith("video2.srt")

    def test_fallback_to_video_idx_selected_srt(self, tmp_path):
        """subtitle_files 给的原始字幕名不存在时，回退到 video_{idx}_selected.srt（Phase 1 生成）"""
        task_id = "test-selected-fallback"
        # 两个视频：video1.mp4（首视频，已处理）、video2.mp4（待批处理）
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video1.mp4", "video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        # Phase 1 生成的筛选字幕：videos_dir 排序后 video2.mp4 索引为 1
        task_dir = temp_dir / task_id
        (task_dir / "video_1_selected.srt").write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n",
            encoding="utf-8",
        )

        captured_args = []

        def mock_process(**kwargs):
            captured_args.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "video2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                # 原始字幕名（磁盘上不存在），强制触发回退1
                "subtitle_files": ["video2.srt"],
            })

        assert len(captured_args) == 1
        assert captured_args[0]["subtitle_path"].endswith("video_1_selected.srt")

    def test_selected_srt_uses_upload_order_not_sorted(self, tmp_path):
        """上传序与文件名字典序相反时，回退1 应按上传序定位 selected.srt（防止字幕错配）"""
        task_id = "test-upload-order"
        # 磁盘上两个视频；videos_dir 字典序为 a.mp4(0), b.mp4(1)
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["a.mp4", "b.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 上传序是 b.mp4(vi=0, 首视频), a.mp4(vi=1) —— 与字典序相反。
        # 因此 a.mp4 的筛选字幕是 video_1_selected.srt（前端按上传序命名）。
        process_module.task_store[task_id] = {
            "video_names_order": ["b.mp4", "a.mp4"],
            "select_recommended_only": False,
        }

        task_dir = temp_dir / task_id
        # a.mp4 的字幕（上传序 vi=1）
        (task_dir / "video_1_selected.srt").write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nA-subs\n", encoding="utf-8",
        )
        # b.mp4 的字幕（上传序 vi=0）—— 若按字典序错算，a.mp4 会错配到这个
        (task_dir / "video_0_selected.srt").write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nB-subs\n", encoding="utf-8",
        )

        captured_args = []

        def mock_process(**kwargs):
            captured_args.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "a"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["a.mp4"],
                "subtitle_files": ["a.srt"],  # 原始名不存在，触发回退1
            })

        assert len(captured_args) == 1
        # 必须命中 a.mp4 自己的 video_1_selected.srt，而非字典序错算的 video_0
        assert captured_args[0]["subtitle_path"].endswith("video_1_selected.srt")

    def test_empty_subtitle_triggers_whisper_path(self, tmp_path):
        """空字符串字幕应传空字符串给 _process_video_to_media（触发 Whisper）"""
        task_id = "test-whisper"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        captured_args = []

        def mock_process(**kwargs):
            captured_args.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "video2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                "subtitle_files": [""],
            })

        assert captured_args[0]["subtitle_path"] == ""

    def test_fallback_to_stem_matching(self, tmp_path):
        """subtitle_files 未指定时，回退到按视频 stem 匹配字幕文件"""
        task_id = "test-fallback"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["video2.mp4"])
        process_module.TEMP_DIR = temp_dir

        # 在 task_dir 下放一个 video2.ass 字幕
        task_dir = temp_dir / task_id
        (task_dir / "video2.ass").write_text("[Script Info]\n", encoding="utf-8")

        captured_args = []

        def mock_process(**kwargs):
            captured_args.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "video2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["video2.mp4"],
                # 不传 subtitle_files，触发回退匹配
            })

        assert captured_args[0]["subtitle_path"].endswith("video2.ass")


# ─── 机器翻译批处理透传测试（E2E-4）─────────────────────────────


class TestBatchMTPassthrough:
    """验证 batch_process 端点把机器翻译参数透传到每个视频的 _process_video_to_media，
    确保批处理模式下每张卡片都能拿到翻译。"""

    def test_mt_params_passed_to_each_video(self, tmp_path):
        """mt_service / mt_api_key / mt_api_base / mt_model_name 透传给每个视频的处理调用"""
        task_id = "test-mt-passthrough"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["v2.mp4", "v3.mp4"])
        process_module.TEMP_DIR = temp_dir

        captured = []

        def mock_process(**kwargs):
            captured.append(kwargs)
            stem = Path(kwargs["video_path"]).stem
            return [{"index": 1, "text": "hi", "translation": "你好",
                     "audio_path": "", "screenshot_path": ""}], stem

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4", "v3.mp4"],
                "subtitle_files": ["", ""],
                "mt_service": "deepl",
                "mt_api_key": "deepl-key-789",
                "mt_api_base": "https://api.deepl.com",
                "mt_model_name": "deepl-pro",
            })

        # 两个视频都应收到完整的 MT 参数（缺一会导致部分卡片无翻译）
        assert len(captured) == 2
        for kw in captured:
            assert kw["mt_service"] == "deepl"
            assert kw["mt_api_key"] == "deepl-key-789"
            assert kw["mt_api_base"] == "https://api.deepl.com"
            assert kw["mt_model_name"] == "deepl-pro"

    def test_no_mt_passes_none(self, tmp_path):
        """未配置 MT 时透传 None，不会误触发翻译"""
        task_id = "test-mt-none"
        temp_dir, _ = _make_fake_task(tmp_path, task_id, ["v2.mp4"])
        process_module.TEMP_DIR = temp_dir

        captured = []

        def mock_process(**kwargs):
            captured.append(kwargs)
            return [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}], "v2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4"],
                "subtitle_files": [""],
            })

        assert len(captured) == 1
        assert captured[0]["mt_service"] is None

    def test_mt_cards_carry_translation_into_manifest(self, tmp_path):
        """MT 翻译后的卡片（带 translation）合并进 manifest，供打包"""
        task_id = "test-mt-manifest"
        temp_dir, output_dir = _make_fake_task(tmp_path, task_id, ["v2.mp4"])
        process_module.TEMP_DIR = temp_dir

        def mock_process(**kwargs):
            return [
                {"index": 10001, "text": "Hello", "translation": "你好",
                 "audio_path": "", "screenshot_path": ""},
                {"index": 10002, "text": "World", "translation": "世界",
                 "audio_path": "", "screenshot_path": ""},
            ], "v2"

        with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
            client.post("/api/process/batch-process", json={
                "task_id": task_id,
                "video_names": ["v2.mp4"],
                "subtitle_files": [""],
                "mt_service": "bing",
            })

        manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
        v2_cards = [c for c in manifest["processed"] if c.get("video_stem") == "v2"]
        assert len(v2_cards) == 2
        assert all(c["translation"] for c in v2_cards)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
