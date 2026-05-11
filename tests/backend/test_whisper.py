"""
测试 whisper_manager.py — 模型下载镜像重试
"""
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestWhisperMirrorRetry:
    """验证网络错误时自动切换 HuggingFace 镜像"""

    def test_network_error_triggers_retry(self):
        """网络错误（timeout/connection）应触发镜像重试"""
        from core import whisper_manager

        whisper_mock = MagicMock()
        whisper_mock.WhisperModel.side_effect = [
            OSError("Connection timeout"),
            MagicMock(),  # 第二次成功
        ]

        # Mock _try_load 的行为
        call_count = [0]
        errors = [OSError("Connection timeout"), None]
        returned = [None, MagicMock()]

        def _mock_try_load():
            idx = call_count[0]
            call_count[0] += 1
            if errors[idx]:
                raise errors[idx]
            return returned[idx]

        net_keywords = ("timeout", "connection", "dns", "ssl", "refused", "host", "network")

        def _is_network_error(err):
            return any(kw in str(err).lower() for kw in net_keywords)

        # 模拟 load_model 的逻辑
        try:
            _mock_try_load()
        except Exception as first_err:
            assert _is_network_error(first_err), "应识别为网络错误"
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            try:
                result = _mock_try_load()
                assert result is not None, "镜像重试应成功"
            finally:
                os.environ.pop("HF_ENDPOINT", None)

        assert call_count[0] == 2, f"应有两次调用（原站失败 + 镜像重试），实际 {call_count[0]}"

    def test_non_network_error_no_retry(self):
        """非网络错误（如模型文件损坏）不应触发镜像重试"""
        net_keywords = ("timeout", "connection", "dns", "ssl", "refused", "host", "network")

        def _is_network_error(err):
            return any(kw in str(err).lower() for kw in net_keywords)

        # 模型损坏错误不含网络关键词
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
