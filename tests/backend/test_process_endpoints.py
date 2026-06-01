"""
集成测试：process.py 的辅助端点和工具函数

覆盖：
1. _to_url 和 _build_cards 辅助函数
2. cleanup_output 端点 - 任务清理
3. export_zip_with_media 端点 - ZIP 导出
4. generate_apkg_endpoint 端点 - Phase 2 打包
5. get_progress 端点 - 进度轮询
6. start_processing 端点 - CLI 触发处理
7. test_connection / list_models 端点 - AI API 连接测试
"""
import json
import sys
import zipfile
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
from api.process import _to_url, _build_cards

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_task_store():
    """每个测试前清空 task_store"""
    process_module.task_store.clear()
    yield
    process_module.task_store.clear()


# ─── _to_url 辅助函数 ──────────────────────────────────────────


class TestToUrl:
    """文件路径转 HTTP URL"""

    def test_normal_output_path(self):
        """包含 output 的路径正确截取"""
        url = _to_url("/data/output/task123/audio/card_0001.mp3")
        assert url == "/output/task123/audio/card_0001.mp3"

    def test_windows_style_path(self):
        """Windows 风格路径也能处理"""
        # 使用 Path 构建确保跨平台兼容
        path = str(Path("C:/Users/test/output/task1/screenshots/card.jpg"))
        url = _to_url(path)
        assert url is not None
        assert "output/" in url
        assert "card.jpg" in url

    def test_empty_string_returns_none(self):
        """空字符串返回 None"""
        assert _to_url("") is None

    def test_no_output_in_path(self):
        """路径中没有 output 时用 parent.name + name"""
        url = _to_url("/data/some/other/file.txt")
        assert url == "/output/other/file.txt"


# ─── _build_cards 辅助函数 ─────────────────────────────────────


class TestBuildCards:
    """处理数据转 ProcessedCard"""

    def test_basic_card_conversion(self):
        """基本字段正确转换（ProcessedCard.sentence 对应 text 字段）"""
        processed = [
            {
                "index": 1,
                "start_sec": 1.0,
                "end_sec": 3.0,
                "text": "Hello",
                "translation": "你好",
                "notes": "问候语",
                "audio_path": "/output/task1/audio/card_0001.mp3",
                "screenshot_path": "/output/task1/screenshots/card_0001.jpg",
            }
        ]
        cards = _build_cards(processed)
        assert len(cards) == 1
        card = cards[0]
        assert card.sentence == "Hello"
        assert card.translation == "你好"
        assert card.notes == "问候语"

    def test_empty_media_paths(self):
        """空媒体路径不崩溃"""
        processed = [
            {
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "test",
                "translation": "测试",
                "notes": "",
                "audio_path": "",
                "screenshot_path": "",
            }
        ]
        cards = _build_cards(processed)
        assert len(cards) == 1
        assert cards[0].audio_path is None  # _to_url("") returns None

    def test_empty_list(self):
        """空列表返回空"""
        assert _build_cards([]) == []

    def test_audio_url_conversion(self):
        """音频路径被转为 HTTP URL"""
        processed = [
            {
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "hi",
                "translation": "",
                "notes": "",
                "audio_path": "/data/output/task1/audio/card_0001.mp3",
                "screenshot_path": "/data/output/task1/screenshots/card_0001.jpg",
            }
        ]
        cards = _build_cards(processed)
        assert cards[0].audio_path == "/output/task1/audio/card_0001.mp3"
        assert cards[0].screenshot_path == "/output/task1/screenshots/card_0001.jpg"


# ─── cleanup_output 端点 ───────────────────────────────────────


class TestCleanupOutput:
    """任务输出目录清理"""

    def test_cleanup_nonexistent_task_returns_404(self):
        """不存在的 task_id 返回 404"""
        resp = client.post("/api/process/cleanup", params={"task_id": "nonexistent"})
        assert resp.status_code == 404

    def test_cleanup_removes_output_dir(self, tmp_path):
        """清理删除 output 目录并从 task_store 移除"""
        task_id = "test-cleanup"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)
        (output_dir / "test.apkg").write_bytes(b"fake apkg")
        (output_dir / "audio").mkdir()
        (output_dir / "audio" / "card.mp3").write_bytes(b"fake audio")

        process_module.task_store[task_id] = {
            "status": "completed",
            "output_dir": str(output_dir),
        }

        resp = client.post("/api/process/cleanup", params={"task_id": task_id})
        assert resp.status_code == 200
        data = resp.json()
        assert str(output_dir) in data["cleaned"]
        assert not output_dir.exists()
        assert task_id not in process_module.task_store

    def test_cleanup_missing_output_dir_still_succeeds(self, tmp_path):
        """output_dir 不存在时仍然成功（幂等清理）"""
        task_id = "test-already-cleaned"
        output_dir = tmp_path / "output" / task_id  # 不创建

        process_module.task_store[task_id] = {
            "status": "completed",
            "output_dir": str(output_dir),
        }

        resp = client.post("/api/process/cleanup", params={"task_id": task_id})
        assert resp.status_code == 200
        assert task_id not in process_module.task_store


# ─── export_zip_with_media 端点 ─────────────────────────────────


class TestExportZip:
    """带媒体文件的 ZIP 导出"""

    def test_export_nonexistent_task_returns_404(self):
        """不存在的任务返回 404"""
        resp = client.get("/api/process/export-zip/nonexistent")
        assert resp.status_code == 404

    def test_export_incomplete_task_returns_404(self):
        """未完成的任务返回 404"""
        task_id = "test-incomplete"
        process_module.task_store[task_id] = {
            "status": "processing",
            "result": None,
        }
        resp = client.get(f"/api/process/export-zip/{task_id}")
        assert resp.status_code == 404

    def test_export_creates_zip_with_media(self, tmp_path):
        """导出 ZIP 包含 CSV、音频和截图"""
        task_id = "test-export"
        output_dir = tmp_path / "output" / task_id
        audio_dir = output_dir / "audio"
        ss_dir = output_dir / "screenshots"
        audio_dir.mkdir(parents=True)
        ss_dir.mkdir(parents=True)

        # 创建媒体文件
        (audio_dir / "card_0001.mp3").write_bytes(b"fake audio 1")
        (audio_dir / "card_0002.mp3").write_bytes(b"fake audio 2")
        (ss_dir / "card_0001.jpg").write_bytes(b"fake image 1")
        (ss_dir / "card_0002.jpg").write_bytes(b"fake image 2")

        process_module.task_store[task_id] = {
            "status": "completed",
            "output_dir": str(output_dir),
            "result": {
                "video_name": "test_video.mp4",
                "merge": True,
                "cards": [
                    {"index": 1, "text": "Card 1", "audio_path": "", "screenshot_path": ""},
                    {"index": 2, "text": "Card 2", "audio_path": "", "screenshot_path": ""},
                ],
            },
        }

        resp = client.get(f"/api/process/export-zip/{task_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"

        # 验证 ZIP 内容
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(resp.content)

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = zf.namelist()
            assert "cards.csv" in names
            assert "audio/card_0001.mp3" in names
            assert "audio/card_0002.mp3" in names
            assert "screenshots/card_0001.jpg" in names
            assert "screenshots/card_0002.jpg" in names

    def test_export_without_media_dirs(self, tmp_path):
        """output_dir 没有 audio/screenshots 子目录时只包含 CSV"""
        task_id = "test-no-media"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)

        process_module.task_store[task_id] = {
            "status": "completed",
            "output_dir": str(output_dir),
            "result": {
                "video_name": "test.mp4",
                "merge": True,
                "cards": [{"index": 1, "text": "hi", "audio_path": "", "screenshot_path": ""}],
            },
        }

        resp = client.get(f"/api/process/export-zip/{task_id}")
        assert resp.status_code == 200

        zip_path = tmp_path / "no_media.zip"
        zip_path.write_bytes(resp.content)

        with zipfile.ZipFile(str(zip_path), "r") as zf:
            names = zf.namelist()
            assert "cards.csv" in names
            # 没有音频和截图目录
            assert not any(n.startswith("audio/") for n in names)


# ─── generate_apkg_endpoint 端点 ────────────────────────────────


class TestGenerateApkgEndpoint:
    """Phase 2 打包端点"""

    def test_nonexistent_task_returns_404(self):
        """不存在的任务返回 404"""
        resp = client.post("/api/process/generate-apkg", data={"task_id": "nonexistent"})
        assert resp.status_code == 404

    def test_wrong_status_returns_400(self):
        """状态不正确返回 400"""
        task_id = "test-wrong-status"
        process_module.task_store[task_id] = {
            "status": "processing",  # 不是 awaiting_styles
        }
        resp = client.post("/api/process/generate-apkg", data={"task_id": task_id})
        assert resp.status_code == 400

    def test_successful_merge_mode_pack(self, tmp_path):
        """合并模式打包成功"""
        task_id = "test-pack-merge"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)

        process_module.task_store[task_id] = {
            "status": "awaiting_styles",
            "output_dir": str(output_dir),
        }

        mock_result = {
            "cards_count": 5,
            "apkg_path": str(output_dir / "test.apkg"),
            "processed": [
                {"index": i, "text": f"Card {i}", "translation": f"翻译{i}",
                 "start_sec": i, "end_sec": i+1, "notes": "",
                 "audio_path": "", "screenshot_path": ""}
                for i in range(1, 6)
            ],
        }

        with patch("api.process.generate_apkg", return_value=mock_result):
            resp = client.post("/api/process/generate-apkg", data={
                "task_id": task_id,
                "card_styles": '["basic"]',
                "theme": "default",
            })

        assert resp.status_code == 200

        # 等待后台线程完成
        import time
        time.sleep(0.5)

        # 验证 task_store 更新
        task = process_module.task_store[task_id]
        assert task["status"] == "completed"
        assert task["result"]["cards_count"] == 5
        assert "apkg_url" in task["result"]

    def test_successful_independent_mode_pack(self, tmp_path):
        """独立模式打包成功"""
        task_id = "test-pack-independent"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)

        process_module.task_store[task_id] = {
            "status": "awaiting_styles",
            "output_dir": str(output_dir),
        }

        mock_result = {
            "total_cards": 10,
            "apkg_paths": [
                str(output_dir / "video1.apkg"),
                str(output_dir / "video2.apkg"),
            ],
            "results": [
                {
                    "video_name": "video1",
                    "cards_count": 6,
                    "apkg_path": str(output_dir / "video1.apkg"),
                    "processed": [
                        {"index": i, "text": f"V1 {i}", "translation": "",
                         "start_sec": 0, "end_sec": 1, "notes": "",
                         "audio_path": "", "screenshot_path": ""}
                        for i in range(6)
                    ],
                },
                {
                    "video_name": "video2",
                    "cards_count": 4,
                    "apkg_path": str(output_dir / "video2.apkg"),
                    "processed": [
                        {"index": i, "text": f"V2 {i}", "translation": "",
                         "start_sec": 0, "end_sec": 1, "notes": "",
                         "audio_path": "", "screenshot_path": ""}
                        for i in range(4)
                    ],
                },
            ],
        }

        with patch("api.process.generate_apkg", return_value=mock_result):
            resp = client.post("/api/process/generate-apkg", data={
                "task_id": task_id,
                "card_styles": '["basic"]',
                "theme": "default",
            })

        assert resp.status_code == 200

        import time
        time.sleep(0.5)

        task = process_module.task_store[task_id]
        assert task["status"] == "completed"
        assert task["result"]["merge"] is False
        assert task["result"]["total_cards"] == 10
        assert len(task["result"]["videos"]) == 2

    def test_pack_failure_sets_error_status(self, tmp_path):
        """打包失败时设置 error 状态"""
        task_id = "test-pack-fail"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)

        process_module.task_store[task_id] = {
            "status": "awaiting_styles",
            "output_dir": str(output_dir),
        }

        with patch("api.process.generate_apkg", side_effect=RuntimeError("genanki 崩溃")):
            resp = client.post("/api/process/generate-apkg", data={
                "task_id": task_id,
                "theme": "default",
            })

        assert resp.status_code == 200

        import time
        time.sleep(0.5)

        task = process_module.task_store[task_id]
        assert task["status"] == "error"
        assert "打包失败" in task["message"]

    def test_invalid_card_styles_json(self, tmp_path):
        """card_styles JSON 解析失败时回退为列表"""
        task_id = "test-bad-json"
        output_dir = tmp_path / "output" / task_id
        output_dir.mkdir(parents=True)

        process_module.task_store[task_id] = {
            "status": "awaiting_styles",
            "output_dir": str(output_dir),
        }

        mock_result = {
            "cards_count": 1,
            "apkg_path": str(output_dir / "test.apkg"),
            "processed": [
                {"index": 1, "text": "hi", "translation": "", "start_sec": 0,
                 "end_sec": 1, "notes": "", "audio_path": "", "screenshot_path": ""}
            ],
        }

        with patch("api.process.generate_apkg", return_value=mock_result) as mock_gen:
            resp = client.post("/api/process/generate-apkg", data={
                "task_id": task_id,
                "card_styles": "not-valid-json",
                "theme": "default",
            })

        assert resp.status_code == 200

        # 验证 card_styles 参数被当作单个字符串列表传递
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["card_styles"] == ["not-valid-json"]


# ─── get_progress 端点 ─────────────────────────────────────────


class TestGetProgress:
    """进度轮询端点"""

    def test_progress_nonexistent_task_returns_404(self):
        """不存在的 task_id 返回 404"""
        resp = client.get("/api/process/progress/nonexistent")
        assert resp.status_code == 404

    def test_progress_processing_task(self):
        """处理中的任务返回完整进度信息"""
        task_id = "test-progress"
        process_module.task_store[task_id] = {
            "status": "processing",
            "step": 3,
            "total_steps": 8,
            "message": "AI 标注中...",
            "details": {"processed": 10, "total": 30},
        }

        resp = client.get(f"/api/process/progress/{task_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == task_id
        assert data["status"] == "processing"
        assert data["step"] == 3
        assert data["total_steps"] == 8
        assert data["message"] == "AI 标注中..."
        assert data["details"]["processed"] == 10

    def test_progress_completed_includes_result(self):
        """已完成的任务附带 result 字段"""
        task_id = "test-done"
        process_module.task_store[task_id] = {
            "status": "completed",
            "step": 1,
            "total_steps": 1,
            "message": "完成",
            "details": None,
            "result": {"cards_count": 42, "apkg_url": "/output/test.apkg"},
        }

        resp = client.get(f"/api/process/progress/{task_id}")
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["cards_count"] == 42

    def test_progress_error_includes_error_info(self):
        """失败的任务返回 error 和 error_code"""
        task_id = "test-error"
        process_module.task_store[task_id] = {
            "status": "error",
            "step": 0,
            "total_steps": 0,
            "message": "处理失败",
            "details": None,
            "error": "AI API 超时",
            "error_code": "AI_TIMEOUT",
        }

        resp = client.get(f"/api/process/progress/{task_id}")
        data = resp.json()
        assert data["status"] == "error"
        assert data["error"] == "AI API 超时"
        assert data["error_code"] == "AI_TIMEOUT"

    def test_progress_awaiting_styles_includes_result(self):
        """等待样式选择的任务也附带 result（前端需要判断是否显示样式面板）"""
        task_id = "test-awaiting"
        process_module.task_store[task_id] = {
            "status": "awaiting_styles",
            "step": 1,
            "total_steps": 2,
            "message": "媒体处理完成，请选择样式",
            "details": None,
            "result": {"cards_count": 100},
        }

        resp = client.get(f"/api/process/progress/{task_id}")
        data = resp.json()
        assert data["status"] == "awaiting_styles"
        assert "result" in data


# ─── start_processing 端点 ──────────────────────────────────────


class TestStartProcessing:
    """CLI 触发的视频处理端点"""

    def test_nonexistent_video_returns_404(self, tmp_path):
        """视频文件不存在返回 404"""
        resp = client.post("/api/process/start", params={
            "video_file_path": str(tmp_path / "nonexistent.mp4"),
            "subtitle_file_path": str(tmp_path / "sub.srt"),
        })
        assert resp.status_code == 404
        assert "视频" in resp.json()["detail"]

    def test_nonexistent_subtitle_returns_404(self, tmp_path):
        """字幕文件不存在返回 404"""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video")

        resp = client.post("/api/process/start", params={
            "video_file_path": str(video_file),
            "subtitle_file_path": str(tmp_path / "missing.srt"),
        })
        assert resp.status_code == 404
        assert "字幕" in resp.json()["detail"]

    def test_successful_processing(self, tmp_path):
        """正常处理返回 ProcessResult"""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video")
        subtitle_file = tmp_path / "video.srt"
        subtitle_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")

        mock_result = {
            "cards_count": 10,
            "apkg_path": str(tmp_path / "output" / "test.apkg"),
            "processed": [
                {"text": f"Card {i}", "translation": f"翻译{i}",
                 "start_sec": i, "end_sec": i+1, "notes": "",
                 "audio_path": "", "screenshot_path": ""}
                for i in range(10)
            ],
        }

        with patch("api.process.process_cards", return_value=mock_result):
            resp = client.post("/api/process/start", params={
                "video_file_path": str(video_file),
                "subtitle_file_path": str(subtitle_file),
                "output_dir": str(tmp_path / "output"),
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["cards_count"] == 10

    def test_processing_failure_returns_500(self, tmp_path):
        """处理失败返回 500"""
        video_file = tmp_path / "video.mp4"
        video_file.write_bytes(b"fake video")
        subtitle_file = tmp_path / "video.srt"
        subtitle_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")

        with patch("api.process.process_cards", side_effect=RuntimeError("处理崩溃")):
            resp = client.post("/api/process/start", params={
                "video_file_path": str(video_file),
                "subtitle_file_path": str(subtitle_file),
            })

        assert resp.status_code == 500


# ─── test_connection 端点 ───────────────────────────────────────


class TestConnectionEndpoint:
    """AI API 连接测试"""

    def test_valid_connection(self):
        """有效 API key 返回 valid=True"""
        mock_completion = MagicMock()

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_completion
            mock_openai.return_value = mock_client

            resp = client.post("/api/process/test-connection", params={
                "api_key": "sk-test-valid-key",
                "api_base": "https://api.deepseek.com",
                "model_name": "deepseek-chat",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert "连接成功" in data["message"]

    def test_invalid_api_key(self):
        """无效 API key 返回 valid=False"""
        from openai import AuthenticationError
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = AuthenticationError(
                "Invalid API key", response=mock_response, body=None
            )
            mock_openai.return_value = mock_client

            resp = client.post("/api/process/test-connection", params={
                "api_key": "sk-invalid-key",
            })

        data = resp.json()
        assert data["valid"] is False


# ─── list_models 端点 ──────────────────────────────────────────


class TestListModels:
    """AI 模型列表获取"""

    def test_list_models_success(self):
        """成功获取模型列表"""
        mock_model_1 = MagicMock()
        mock_model_1.id = "deepseek-chat"
        mock_model_2 = MagicMock()
        mock_model_2.id = "deepseek-reasoner"
        mock_model_3 = MagicMock()
        mock_model_3.id = "gpt-4o"

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.models.list.return_value = [mock_model_1, mock_model_2, mock_model_3]
            mock_openai.return_value = mock_client

            resp = client.post("/api/process/list-models", params={
                "api_key": "sk-test-key",
            })

        assert resp.status_code == 200
        models = resp.json()["models"]
        # deepseek 模型排在前面
        assert models[0].startswith("deepseek")
        assert "gpt-4o" in models

    def test_list_models_failure_returns_500(self):
        """获取模型列表失败返回 500"""
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.models.list.side_effect = Exception("Network error")
            mock_openai.return_value = mock_client

            resp = client.post("/api/process/list-models", params={
                "api_key": "sk-test-key",
            })

        assert resp.status_code == 500
        assert "获取模型列表失败" in resp.json()["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
