"""
subtitles API 端点测试
覆盖：上传、解析、示例数据、ffmpeg/whisper 状态、ASR 引擎列表
"""

import sys
from pathlib import Path

# 设置路径 - 在导入 app 前
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(TEST_ROOT / "backend"))

import pytest
from unittest.mock import patch, Mock
import io
import json
import threading
import time

from fastapi.testclient import TestClient
from fastapi import FastAPI

# 构建最小 app 仅挂载 subtitles router
from api import subtitles as subtitles_module

app = FastAPI()
app.include_router(subtitles_module.router, prefix="/api/subtitles")


@pytest.fixture
def client():
    return TestClient(app)


# ── 辅助 ────────────────────────────────────────────────

VALID_SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:05,000 --> 00:00:08,000
Second subtitle

3
00:00:10,000 --> 00:00:12,500
Third one
"""

SHORT_SRT_CONTENT = """\
1
00:00:01,000 --> 00:00:01,500
Too short

2
00:00:05,000 --> 00:00:08,000
OK duration
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /upload
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestUploadSubtitle:
    """字幕上传端点"""

    def test_upload_valid_srt(self, client):
        """上传有效 SRT 文件"""
        files = {"file": ("test.srt", io.BytesIO(VALID_SRT_CONTENT.encode("utf-8")), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["filtered"] == 3
        assert len(data["subtitles"]) == 3

    def test_upload_filters_short_subtitles(self, client):
        """上传时自动过滤短字幕"""
        files = {"file": ("short.srt", io.BytesIO(SHORT_SRT_CONTENT.encode("utf-8")), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files, params={"min_duration": 1.0})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["filtered"] == 1  # 只保留 1 条

    def test_upload_custom_min_duration(self, client):
        """自定义 min_duration 参数"""
        files = {"file": ("short.srt", io.BytesIO(SHORT_SRT_CONTENT.encode("utf-8")), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files, params={"min_duration": 0.1})

        assert resp.status_code == 200
        data = resp.json()
        assert data["filtered"] == 2  # 全部保留

    def test_upload_non_srt_rejected(self, client):
        """非 .srt 文件应被拒绝"""
        files = {"file": ("test.txt", io.BytesIO(b"not srt"), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files)

        assert resp.status_code == 400
        assert "只支持 .srt" in resp.json()["detail"]

    def test_upload_empty_srt(self, client):
        """上传空 SRT 文件"""
        files = {"file": ("empty.srt", io.BytesIO(b""), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["filtered"] == 0

    def test_upload_subtitle_item_fields(self, client):
        """字幕项应包含完整字段"""
        files = {"file": ("test.srt", io.BytesIO(VALID_SRT_CONTENT.encode("utf-8")), "text/plain")}
        resp = client.post("/api/subtitles/upload", files=files)

        assert resp.status_code == 200
        sub = resp.json()["subtitles"][0]
        assert "index" in sub
        assert "start_sec" in sub
        assert "end_sec" in sub
        assert "text" in sub
        assert "duration" in sub
        assert sub["duration"] > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /example
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestExampleSubtitles:
    """示例字幕端点"""

    def test_get_example(self, client):
        """获取示例字幕"""
        resp = client.get("/api/subtitles/example")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["filtered"] == 3
        assert len(data["subtitles"]) == 3

    def test_example_subtitle_content(self, client):
        """示例字幕内容验证"""
        resp = client.get("/api/subtitles/example")
        subs = resp.json()["subtitles"]

        assert subs[0]["text"] == "Hello, how are you?"
        assert subs[0]["index"] == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /ffmpeg/status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFFmpegStatus:
    """ffmpeg 状态检测"""

    @patch("api.subtitles.subprocess_run")
    def test_ffmpeg_installed(self, mock_run, client):
        """ffmpeg 已安装"""
        mock_run.return_value = Mock(returncode=0, stdout="ffmpeg version 5.0")
        resp = client.get("/api/subtitles/ffmpeg/status")

        assert resp.status_code == 200
        assert resp.json()["installed"] is True

    @patch("api.subtitles.subprocess_run")
    def test_ffmpeg_not_found(self, mock_run, client):
        """ffmpeg 未找到"""
        mock_run.side_effect = FileNotFoundError()
        resp = client.get("/api/subtitles/ffmpeg/status")

        assert resp.status_code == 200
        assert resp.json()["installed"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /whisper/status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestWhisperStatus:
    """Whisper 状态检测"""

    @patch("api.subtitles.is_whisper_installed")
    def test_whisper_installed(self, mock_check, client):
        """Whisper 已安装"""
        mock_check.return_value = True
        resp = client.get("/api/subtitles/whisper/status")

        assert resp.status_code == 200
        assert resp.json()["installed"] is True

    @patch("api.subtitles.is_whisper_installed")
    def test_whisper_not_installed(self, mock_check, client):
        """Whisper 未安装"""
        mock_check.return_value = False
        resp = client.get("/api/subtitles/whisper/status")

        assert resp.status_code == 200
        assert resp.json()["installed"] is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /whisper/install
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestWhisperInstall:
    """Whisper 安装端点"""

    @patch("api.subtitles.is_whisper_installed")
    def test_already_installed(self, mock_check, client):
        """Whisper 已安装时应直接返回"""
        mock_check.return_value = True
        resp = client.post("/api/subtitles/whisper/install")

        assert resp.status_code == 200
        assert resp.json()["status"] == "already_installed"

    @patch("api.subtitles.install_whisper")
    @patch("api.subtitles.is_whisper_installed")
    def test_install_success(self, mock_check, mock_install, client):
        """安装成功"""
        mock_check.return_value = False
        mock_install.return_value = (True, "")
        resp = client.post("/api/subtitles/whisper/install")

        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("api.subtitles.install_whisper")
    @patch("api.subtitles.is_whisper_installed")
    def test_install_failure(self, mock_check, mock_install, client):
        """安装失败"""
        mock_check.return_value = False
        mock_install.return_value = (False, "pip install failed")
        resp = client.post("/api/subtitles/whisper/install")

        assert resp.status_code == 500
        assert "安装失败" in resp.json()["detail"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /asr/engines
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestASREngines:
    """ASR 引擎列表"""

    @patch("core.asr.get_available_engines")
    def test_list_engines(self, mock_engines, client):
        """列出 ASR 引擎"""
        mock_engines.return_value = [
            {"id": "faster_whisper", "name": "Faster Whisper", "available": True},
            {"id": "bcut", "name": "必剪 ASR", "available": True},
        ]
        resp = client.get("/api/subtitles/asr/engines")

        assert resp.status_code == 200
        engines = resp.json()["engines"]
        assert len(engines) == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /ai-recommend (validation)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAIRecommendValidation:
    """AI 推荐端点参数校验"""

    def test_missing_api_key(self, client, monkeypatch):
        """缺少 API Key 应返回 400"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        resp = client.post("/api/subtitles/ai-recommend", json={
            "subtitles": [{"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hi"}],
        })
        assert resp.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /transcribe cache
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestTranscribeCache:
    """转录字幕缓存"""

    def test_transcribe_uses_cache_by_filename_and_size(self, client, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache" / "subtitles"
        monkeypatch.setattr(subtitles_module, "_get_subtitle_cache_dir", lambda: cache_dir)
        monkeypatch.setattr(subtitles_module, "is_whisper_installed", lambda: True)
        video_bytes = b"same video bytes"
        cache_path = subtitles_module._subtitle_cache_path("movie.mp4", len(video_bytes))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cached_result = {
            "subtitles": [{"index": 1, "start_sec": 0, "end_sec": 1, "text": "Hello", "duration": 1}],
            "total": 1,
            "filtered": 1,
        }
        cache_path.write_text(json.dumps({
            "filename": "movie.mp4",
            "file_size": len(video_bytes),
            "cached_at": time.time(),
            "result": cached_result,
        }), encoding="utf-8")

        with patch("api.subtitles.threading.Thread") as mock_thread:
            resp = client.post(
                "/api/subtitles/transcribe",
                files={"video": ("movie.mp4", io.BytesIO(video_bytes), "video/mp4")},
            )

        assert resp.status_code == 200
        assert resp.json()["cached"] is True
        mock_thread.assert_not_called()
        progress = client.get(f"/api/subtitles/transcribe/progress/{resp.json()['task_id']}")
        assert progress.status_code == 200
        assert progress.json()["result"] == cached_result

    def test_run_transcribe_preserves_bcut_cache_message(self, tmp_path, monkeypatch):
        from api import transcribe as transcribe_module

        video_path = tmp_path / "movie.mp4"
        srt_path = tmp_path / "movie.srt"
        video_path.write_bytes(b"video")
        srt_path.write_text(VALID_SRT_CONTENT, encoding="utf-8")

        class FakeConnection:
            def __init__(self):
                self.messages = [
                    {"step": "transcribing", "progress": 1.0, "transcribed_sec": 3.0, "duration_sec": 3.0, "message": "命中缓存，转录完成"},
                    {"step": "done", "segment_count": 3, "cached": True},
                ]

            def poll(self, _timeout=0):
                return bool(self.messages)

            def recv(self):
                return self.messages.pop(0)

            def close(self):
                pass

        class FakeProcess:
            exitcode = 0

            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def is_alive(self):
                return False

            def join(self, timeout=None):
                pass

        def fake_pipe(duplex=False):
            return FakeConnection(), Mock(close=lambda: None)

        monkeypatch.setattr(transcribe_module.multiprocessing, "Pipe", fake_pipe)
        monkeypatch.setattr(transcribe_module.multiprocessing, "Process", FakeProcess)

        store = {}
        lock = threading.Lock()
        transcribe_module.run_transcribe(
            "task-cache",
            str(video_path),
            str(srt_path),
            "bcut",
            "base",
            None,
            1.0,
            store,
            lock,
        )

        assert store["task-cache"]["cached"] is True
        assert store["task-cache"]["message"] == "已使用缓存字幕，共 3 条"
        assert store["task-cache"]["result"]["filtered"] == 3

    def test_run_transcribe_ignores_closed_pipe_after_success(self, tmp_path, monkeypatch):
        from api import transcribe as transcribe_module

        video_path = tmp_path / "movie.mp4"
        srt_path = tmp_path / "movie.srt"
        video_path.write_bytes(b"video")
        srt_path.write_text(VALID_SRT_CONTENT, encoding="utf-8")

        class ClosedPipeConnection:
            def poll(self, _timeout=0):
                raise OSError("[WinError 109] 管道已结束。")

            def recv(self):
                raise AssertionError("recv should not be called when poll fails")

        class FakeProcess:
            exitcode = 0

            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def is_alive(self):
                return False

            def join(self, timeout=None):
                pass

        def fake_pipe(duplex=False):
            return ClosedPipeConnection(), Mock(close=lambda: None)

        monkeypatch.setattr(transcribe_module.multiprocessing, "Pipe", fake_pipe)
        monkeypatch.setattr(transcribe_module.multiprocessing, "Process", FakeProcess)

        store = {}
        lock = threading.Lock()
        transcribe_module.run_transcribe(
            "task-closed-pipe",
            str(video_path),
            str(srt_path),
            "faster_whisper",
            "base",
            None,
            1.0,
            store,
            lock,
        )

        assert store["task-closed-pipe"]["status"] == "completed"
        assert store["task-closed-pipe"]["result"]["filtered"] == 3

    def test_transcribe_force_ignores_cache(self, client, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache" / "subtitles"
        monkeypatch.setattr(subtitles_module, "_get_subtitle_cache_dir", lambda: cache_dir)
        monkeypatch.setattr(subtitles_module, "is_whisper_installed", lambda: True)
        video_bytes = b"same video bytes"
        cache_path = subtitles_module._subtitle_cache_path("movie.mp4", len(video_bytes))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({
            "filename": "movie.mp4",
            "file_size": len(video_bytes),
            "cached_at": time.time(),
            "result": {"subtitles": [], "total": 0, "filtered": 0},
        }), encoding="utf-8")

        with patch("api.subtitles.threading.Thread") as mock_thread:
            resp = client.post(
                "/api/subtitles/transcribe?force_transcribe=true",
                files={"video": ("movie.mp4", io.BytesIO(video_bytes), "video/mp4")},
            )

        assert resp.status_code == 200
        assert "cached" not in resp.json()
        mock_thread.assert_called_once()
