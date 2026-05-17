"""
测试 model_downloader.py — 模型下载模块
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import model_downloader


class TestFindAria2c:
    """aria2c 检测"""

    def test_found_in_path(self):
        """aria2c 在 PATH 中可被找到"""
        with patch.object(model_downloader.shutil, 'which', return_value="/usr/bin/aria2c"):
            result = model_downloader.find_aria2c()
            assert result == "/usr/bin/aria2c"

    def test_not_found(self):
        """aria2c 不在 PATH 中返回 None"""
        with patch.object(model_downloader.shutil, 'which', return_value=None):
            with patch.object(model_downloader.os.path, 'exists', return_value=False):
                result = model_downloader.find_aria2c()
                assert result is None


class TestModelscopeModelMap:
    """ModelScope 模型 ID 映射"""

    def test_tiny_model_id(self):
        assert model_downloader.MODELSCOPE_MODEL_MAP["tiny"] == "pengzhendong/faster-whisper-tiny"

    def test_base_model_id(self):
        assert model_downloader.MODELSCOPE_MODEL_MAP["base"] == "pengzhendong/faster-whisper-base"

    def test_large_v3_model_id(self):
        assert model_downloader.MODELSCOPE_MODEL_MAP["large-v3"] == "pengzhendong/faster-whisper-large-v3"

    def test_common_models_have_mapping(self):
        """常用的 faster-whisper 模型都应有 ModelScope 映射"""
        expected_models = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
        for name in expected_models:
            assert name in model_downloader.MODELSCOPE_MODEL_MAP, f"{name} 缺少 ModelScope 映射"


class TestDownloadFile:
    """直链文件下载"""

    def test_download_with_aria2c(self):
        """aria2c 可用时优先使用"""
        with (
            patch.object(model_downloader, 'find_aria2c', return_value="/usr/bin/aria2c"),
            patch.object(model_downloader, '_download_with_aria2c', return_value=True) as mock_aria2,
        ):
            result = model_downloader.download_file("http://example.com/model.bin", Path("/tmp/model.bin"))
            assert result is True
            mock_aria2.assert_called_once()

    def test_download_fallback_to_requests(self):
        """aria2c 不可用时回退到 requests"""
        with (
            patch.object(model_downloader, 'find_aria2c', return_value=None),
            patch.object(model_downloader, '_download_with_requests', return_value=True) as mock_req,
        ):
            result = model_downloader.download_file("http://example.com/model.bin", Path("/tmp/model.bin"))
            assert result is True
            mock_req.assert_called_once()

    def test_download_requests_with_progress(self):
        """requests 下载应触发进度回调"""
        progress_calls = []

        mock_resp = MagicMock()
        mock_resp.headers = {"content-length": "3000000"}
        mock_resp.iter_content.return_value = [b"x" * 1000000, b"x" * 1000000, b"x" * 1000000]

        with (
            patch.object(model_downloader, 'find_aria2c', return_value=None),
            patch("requests.get", return_value=mock_resp),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "test.bin"
            result = model_downloader._download_with_requests(
                "http://example.com/model.bin", dest,
                progress_callback=lambda downloaded, total: progress_calls.append((downloaded, total)),
            )
            assert result is True
            assert len(progress_calls) >= 3
            # 最后一条进度应报告完成
            assert progress_calls[-1] == (3000000, 3000000)

    def test_download_requests_http_error(self):
        """HTTP 错误时返回 False，不残留 .part 文件"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")

        with (
            patch.object(model_downloader, 'find_aria2c', return_value=None),
            patch("requests.get", return_value=mock_resp),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "test.bin"
            result = model_downloader.download_file("http://example.com/model.bin", dest)
            assert result is False
            assert not dest.exists()
            assert not Path(str(dest) + ".part").exists()


class TestDownloadFromModelscope:
    """ModelScope SDK 下载"""

    def test_not_installed_returns_false(self):
        """modelscope 未安装时返回 False"""
        import builtins as _bi
        _orig = _bi.__import__

        def _block(name, *args, **kwargs):
            if name.startswith("modelscope"):
                raise ImportError(f"No module named '{name}'")
            return _orig(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_block):
            with tempfile.TemporaryDirectory() as tmp:
                result = model_downloader.download_from_modelscope(
                    "pengzhendong/faster-whisper-tiny", Path(tmp) / "test"
                )
                assert result is False

    def test_download_success(self):
        """ModelScope 下载成功后返回 True"""
        mock_snapshot = MagicMock()
        with (
            patch.dict(sys.modules, {
                'modelscope': MagicMock(),
                'modelscope.hub': MagicMock(),
                'modelscope.hub.api': MagicMock(),
                'modelscope.hub.snapshot_download': MagicMock(),
            }),
            patch.object(sys.modules['modelscope.hub.snapshot_download'],
                        'snapshot_download', mock_snapshot),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "faster-whisper-tiny"
            result = model_downloader.download_from_modelscope(
                "pengzhendong/faster-whisper-tiny", dest
            )
            assert result is True
            mock_snapshot.assert_called_once_with("pengzhendong/faster-whisper-tiny", local_dir=str(dest))

    def test_download_failure_cleans_up(self):
        """ModelScope 下载失败时清除不完整文件，返回 False"""
        # 预注入 sys.modules 避免真实 modelscope 导入（会触发 torch 加载报错）
        fake_ms = MagicMock()
        fake_ms.side_effect = RuntimeError("下载中断")

        with (
            patch.dict(sys.modules, {
                'modelscope': MagicMock(),
                'modelscope.hub': MagicMock(),
                'modelscope.hub.api': MagicMock(),
                'modelscope.hub.snapshot_download': MagicMock(),
            }),
            patch.object(sys.modules['modelscope.hub.snapshot_download'],
                        'snapshot_download', fake_ms),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "faster-whisper-tiny"
            dest.mkdir(parents=True)
            (dest / "partial.bin").write_text("incomplete")

            result = model_downloader.download_from_modelscope(
                "pengzhendong/faster-whisper-tiny", dest
            )
            assert result is False
            assert not dest.exists()


class TestDownloadWhisperModel:
    """高层 download_whisper_model 接口"""

    def test_modelscope_success_returns_path(self):
        """ModelScope 下载成功 → 返回模型目录路径"""
        with (
            patch.object(model_downloader, 'download_from_modelscope', return_value=True),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "base"
            result = model_downloader.download_whisper_model("base", dest)
            assert result == dest

    def test_modelscope_fails_tries_direct_download(self):
        """ModelScope 失败 → 尝试直链下载"""
        with (
            patch.object(model_downloader, 'download_from_modelscope', return_value=False),
            patch.object(model_downloader, 'download_file', return_value=True),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "base"
            result = model_downloader.download_whisper_model("base", dest)
            assert result == dest

    def test_unknown_model_skips_modelscope(self):
        """未知模型（无 ModelScope 映射）直接走直链下载"""
        with (
            patch.object(model_downloader, 'download_from_modelscope') as mock_ms,
            patch.object(model_downloader, 'download_file', return_value=True),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "unknown-model"
            result = model_downloader.download_whisper_model("unknown-model", dest)
            # 无 ModelScope 映射，不调用 ModelScope
            mock_ms.assert_not_called()

    def test_all_sources_fail_returns_none(self):
        """所有下载源均失败 → 返回 None"""
        with (
            patch.object(model_downloader, 'download_from_modelscope', return_value=False),
            patch.object(model_downloader, 'download_file', return_value=False),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "base"
            result = model_downloader.download_whisper_model("base", dest)
            assert result is None

    def test_progress_callback_called(self):
        """下载过程应触发进度回调"""
        progress_msgs = []

        with (
            patch.object(model_downloader, 'download_from_modelscope', return_value=True),
            tempfile.TemporaryDirectory() as tmp,
        ):
            dest = Path(tmp) / "base"
            model_downloader.download_whisper_model(
                "base", dest,
                progress_callback=lambda val, msg: progress_msgs.append((val, msg)),
            )
            assert len(progress_msgs) >= 1


class TestGetTotalSize:
    """HEAD 请求获取文件大小"""

    def test_returns_content_length(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"content-length": "12345678"}
        with patch("requests.head", return_value=mock_resp):
            size = model_downloader._get_total_size("http://example.com/model.bin")
            assert size == 12345678

    def test_no_content_length_returns_zero(self):
        mock_resp = MagicMock()
        mock_resp.headers = {}
        with patch("requests.head", return_value=mock_resp):
            size = model_downloader._get_total_size("http://example.com/model.bin")
            assert size == 0

    def test_request_fails_returns_zero(self):
        with patch("requests.head", side_effect=Exception("timeout")):
            size = model_downloader._get_total_size("http://example.com/model.bin")
            assert size == 0
