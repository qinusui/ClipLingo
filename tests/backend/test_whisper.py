"""
测试 whisper_manager.py — 模型下载多源回退与离线模型
"""
import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core import whisper_manager


class TestOfflineModel:
    """离线模型检测与加载"""

    def test_offline_model_detected(self):
        """model.bin 存在时应检测为离线模型"""
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "base"
            model_dir.mkdir(parents=True)
            (model_dir / "model.bin").write_text("fake model")

            # 临时覆盖离线目录
            with patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)):
                result = whisper_manager._check_offline_model("base")
                assert result == model_dir

    def test_offline_model_not_found(self):
        """model.bin 不存在时应返回 None"""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)):
                result = whisper_manager._check_offline_model("large-v3")
                assert result is None

    def test_load_from_offline_model(self):
        """离线模型存在时应优先从本地加载，不触发网络请求"""
        mock_fw = MagicMock()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)),
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
        ):
            model_dir = Path(tmp) / "small"
            model_dir.mkdir(parents=True)
            (model_dir / "model.bin").write_text("fake model")

            whisper_manager.load_model("small")

            mock_fw.WhisperModel.assert_called_once_with(
                str(model_dir), local_files_only=True
            )

    def test_offline_model_corrupt_falls_through(self):
        """离线模型存在但损坏，应继续尝试在线下载源"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = [
            OSError("model.bin invalid header"),  # 离线加载失败
            MagicMock(),  # 在线下载成功
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)),
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
        ):
            model_dir = Path(tmp) / "base"
            model_dir.mkdir(parents=True)
            (model_dir / "model.bin").write_text("corrupt")

            result = whisper_manager.load_model("base")
            assert result is not None
            # 确认调用了两次：第一次离线失败，第二次在线成功
            assert mock_fw.WhisperModel.call_count == 2


class TestMultiSourceDownload:
    """多下载源回退"""

    def test_hf_mirror_first(self):
        """第一个在线源应为 hf-mirror.com"""
        assert whisper_manager.HF_SOURCES[0][0] == "https://hf-mirror.com"

    def test_huggingface_is_last_resort(self):
        """HuggingFace 主站应为最后一个源"""
        assert whisper_manager.HF_SOURCES[-1][0] == "https://huggingface.co"

    def test_second_source_used_when_first_fails(self):
        """第一源失败后尝试第二源"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = [
            OSError("Connection refused"),  # hf-mirror 失败
            MagicMock(),  # HuggingFace 成功
        ]
        with patch.object(whisper_manager, 'get_whisper', return_value=mock_fw):
            result = whisper_manager.load_model("tiny")
            assert result is not None
            assert mock_fw.WhisperModel.call_count == 2

    def test_all_sources_fail_raises_error(self):
        """所有源失败应抛出 ClipLingoError"""
        from errors import ClipLingoError, ErrorCode

        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = OSError("Connection refused")
        with patch.object(whisper_manager, 'get_whisper', return_value=mock_fw):
            try:
                whisper_manager.load_model("tiny")
                assert False, "应抛出异常"
            except ClipLingoError as e:
                assert e.code == ErrorCode.WHISPER_MODEL_FAILED
                assert "离线模型目录" in e.detail
                assert "hf-mirror.com" in e.detail


class TestWhisperMirrorRetry:
    """验证网络错误关键词覆盖（保留原有测试）"""

    def test_non_network_error_no_retry(self):
        """非网络错误不应被误判"""
        net_keywords = ("timeout", "connection", "dns", "ssl", "refused", "host", "network")

        def _is_network_error(err):
            return any(kw in str(err).lower() for kw in net_keywords)

        err = OSError("model file corrupted: invalid header")
        assert not _is_network_error(err), "模型损坏不应被识别为网络错误"

    def test_mirror_fallback_keyword_coverage(self):
        """验证各种典型网络错误都能被识别"""
        net_keywords = ("timeout", "connection", "dns", "ssl", "refused", "host", "network",
                        "unreachable", "reset", "getaddrinfo", "tls", "certificate", "eof",
                        "broken pipe", "nodata", "503", "502", "403")

        def _is_network_error(err):
            return any(kw in str(err).lower() for kw in net_keywords)

        network_errors = [
            "ReadTimeout: HTTPSConnectionPool timeout",
            "Connection refused by remote host",
            "getaddrinfo failed: Name or service not known",
            "SSL: CERTIFICATE_VERIFY_FAILED",
            "huggingface_hub returned 503 Service Unavailable",
            "tls: handshake failure",
            "EOF occurred in violation of protocol",
        ]

        for msg in network_errors:
            assert _is_network_error(Exception(msg)), \
                f"'{msg}' 应被识别为网络错误"

        non_network = [
            "invalid model binary format",
            "ctranslate2: unsupported model version",
        ]

        for msg in non_network:
            assert not _is_network_error(Exception(msg)), \
                f"'{msg}' 不应被识别为网络错误"


class TestAutoDetectSourceOrder:
    """根据网络环境自动调整下载源优先级"""

    def test_mirror_fast_prioritized(self):
        """hf-mirror.com 延迟 < 2s → 国内用户，镜像优先"""
        with patch.object(whisper_manager, '_probe_host', return_value=0.15):
            whisper_manager._cached_source_order = None  # 清除缓存
            result = whisper_manager._get_source_order()
            # hf-mirror 应在第一位
            assert result[0][0] == "https://hf-mirror.com"
            assert result[1][0] == "https://huggingface.co"

    def test_mirror_slow_falls_back(self):
        """hf-mirror.com 延迟 >= 2s → 海外用户，HuggingFace 优先"""
        with patch.object(whisper_manager, '_probe_host', return_value=3.5):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            # HuggingFace 主站应在第一位
            assert result[0][0] == "https://huggingface.co"
            assert result[1][0] == "https://hf-mirror.com"

    def test_mirror_unreachable_falls_back(self):
        """hf-mirror.com 不可达 → HuggingFace 优先"""
        with patch.object(whisper_manager, '_probe_host', return_value=None):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            assert result[0][0] == "https://huggingface.co"
            assert result[1][0] == "https://hf-mirror.com"

    def test_result_is_cached(self):
        """探测结果只计算一次，后续调用走缓存"""
        with patch.object(whisper_manager, '_probe_host', return_value=0.1) as mock_probe:
            whisper_manager._cached_source_order = None
            whisper_manager._get_source_order()
            whisper_manager._get_source_order()
            # 只探测了一次
            assert mock_probe.call_count == 1
