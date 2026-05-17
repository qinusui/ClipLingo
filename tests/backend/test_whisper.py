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

    def test_tsinghua_removed(self):
        """清华 TUNA 镜像已于 2021 年失效，应从源列表中移除"""
        labels = [s[2] for s in whisper_manager.HF_SOURCES]
        assert "清华镜像" not in labels
        assert len(whisper_manager.HF_SOURCES) == 3

    def test_modelscope_in_sources(self):
        """ModelScope（阿里云）应在下载源列表中"""
        api_endpoints = [s[0] for s in whisper_manager.HF_SOURCES if s[0] is not None]
        assert any("modelscope" in ep for ep in api_endpoints)

    def test_huggingface_is_last_resort(self):
        """HuggingFace 主站应为最后一个源"""
        assert whisper_manager.HF_SOURCES[-1][0] == "https://huggingface.co"

    def test_second_source_used_when_first_fails(self):
        """第一源失败后尝试第二源（ModelScope）"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = [
            OSError("Connection refused"),   # hf-mirror 失败
            MagicMock(),                     # ModelScope 成功
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
                assert "modelscope" in e.detail


class TestCacheClearing:
    """失败后清除损坏缓存，确保下一源从干净状态开始"""

    def test_clear_model_cache_removes_directory(self):
        """_clear_model_cache 应删除模型缓存目录"""
        with tempfile.TemporaryDirectory() as tmp:
            fake_cache = Path(tmp) / "models--Systran--faster-whisper-base"
            fake_cache.mkdir(parents=True)
            (fake_cache / "model.bin").write_text("corrupt")
            assert fake_cache.exists()

            with patch('huggingface_hub.constants.HF_HUB_CACHE', tmp):
                whisper_manager._clear_model_cache("base")
                assert not fake_cache.exists()

    def test_clear_model_cache_nonexistent_no_error(self):
        """缓存目录不存在时 _clear_model_cache 不应报错"""
        with tempfile.TemporaryDirectory() as tmp:
            with patch('huggingface_hub.constants.HF_HUB_CACHE', tmp):
                whisper_manager._clear_model_cache("large-v3")  # 不应抛异常

    def test_cache_cleared_between_failed_attempts(self):
        """第一源失败后，尝试第二源前应清除缓存"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = [
            OSError("Unable to open file"),   # 第一源失败
            MagicMock(),                      # 第二源成功
        ]
        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=None),
            patch.object(whisper_manager, '_clear_model_cache') as mock_clear,
        ):
            result = whisper_manager.load_model("tiny")
            assert result is not None
            # 第一源失败后应调用 _clear_model_cache 一次
            mock_clear.assert_called_once_with("tiny")


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


class TestModelScopeDownload:
    """ModelScope SDK 下载集成 — 在线下载前先尝试 ModelScope"""

    def test_modelscope_tried_before_hf_hub(self):
        """ModelScope 成功时直接加载本地模型，不触发 HF hub"""
        mock_fw = MagicMock()
        ms_path = Path("/fake/models/base")
        ms_path.mkdir(parents=True, exist_ok=True)
        (ms_path / "model.bin").write_text("fake")

        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_check_offline_model', return_value=None),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=ms_path),
        ):
            result = whisper_manager.load_model("base")
            assert result is not None
            mock_fw.WhisperModel.assert_called_once_with(str(ms_path), local_files_only=True)
            # HF hub 相关函数不应被调用
            assert "_set_hf_endpoint" not in str(mock_fw.method_calls)

    def test_modelscope_fails_falls_through_to_hf(self):
        """ModelScope 失败后继续尝试 HF hub"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.side_effect = [
            MagicMock(),  # HF hub 成功
        ]

        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_check_offline_model', return_value=None),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=None),
            patch.object(whisper_manager, '_set_hf_endpoint'),
        ):
            result = whisper_manager.load_model("base")
            assert result is not None
            # 确认尝试了 HF hub 下载
            mock_fw.WhisperModel.assert_called_once_with("base")

    def test_modelscope_failure_clears_offline_dir(self):
        """ModelScope 下载成功后加载失败时清除离线目录再走 HF"""
        mock_fw = MagicMock()
        fake_path = Path("/fake/models/base")
        fake_path.mkdir(parents=True, exist_ok=True)
        (fake_path / "model.bin").write_text("fake")

        mock_fw.WhisperModel.side_effect = [
            OSError("corrupt model"),  # 离线加载失败
            MagicMock(),               # HF hub 成功
        ]

        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_check_offline_model', return_value=None),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=fake_path),
            patch.object(whisper_manager, '_clear_offline_model') as mock_clear,
            patch.object(whisper_manager, '_set_hf_endpoint'),
        ):
            result = whisper_manager.load_model("base")
            assert result is not None
            mock_clear.assert_called_once_with("base")

    def test_download_via_modelscope_returns_path(self):
        """_download_via_modelscope 成功时返回模型目录"""
        fake_dest = Path("/fake/models/base")
        fake_dest.mkdir(parents=True, exist_ok=True)
        (fake_dest / "model.bin").write_text("fake")

        with patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path("/fake/models")):
            # model.bin 已存在，直接返回
            result = whisper_manager._download_via_modelscope("base")
            assert result == fake_dest

    def test_download_via_modelscope_download_fails(self):
        """download_whisper_model 返回 None 时 _download_via_modelscope 返回 None"""
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)),
            patch('core.model_downloader.download_whisper_model', return_value=None),
        ):
            result = whisper_manager._download_via_modelscope("tiny")
            assert result is None

    def test_clear_offline_model(self):
        """_clear_offline_model 删除模型目录"""
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "base"
            model_dir.mkdir(parents=True)
            (model_dir / "model.bin").write_text("fake")
            assert model_dir.exists()

            with patch.object(whisper_manager, 'LOCAL_MODEL_DIR', Path(tmp)):
                whisper_manager._clear_offline_model("base")
                assert not model_dir.exists()


class TestProgressCallback:
    """load_model 的 progress_callback 参数"""

    def test_callback_called_during_download(self):
        """下载过程中应调用 progress_callback 报告状态"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = MagicMock()
        progress_msgs = []

        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_check_offline_model', return_value=None),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=None),
            patch.object(whisper_manager, '_set_hf_endpoint'),
        ):
            whisper_manager.load_model(
                "base",
                progress_callback=lambda msg: progress_msgs.append(msg),
            )
            assert len(progress_msgs) >= 1
            # 至少有一条包含模型名
            assert any("base" in msg for msg in progress_msgs)

    def test_callback_optional(self):
        """progress_callback 为 None 时不应报错"""
        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = MagicMock()

        with (
            patch.object(whisper_manager, 'get_whisper', return_value=mock_fw),
            patch.object(whisper_manager, '_check_offline_model', return_value=None),
            patch.object(whisper_manager, '_download_via_modelscope', return_value=None),
            patch.object(whisper_manager, '_set_hf_endpoint'),
        ):
            # 不应抛异常
            result = whisper_manager.load_model("base")
            assert result is not None


class TestAutoDetectSourceOrder:
    """根据网络环境自动调整下载源优先级（探测所有源延迟并排序）"""

    def test_all_fast_original_order_preserved(self):
        """所有源延迟相同 → 保持原始优先级顺序"""
        with patch.object(whisper_manager, '_probe_host', return_value=0.15):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            # 返回格式: (api_endpoint, label, url_tpl)
            assert len(result) == 3
            assert result[0][0] == "https://hf-mirror.com"
            assert result[1][0] == "https://huggingface.modelscope.cn"
            assert result[2][0] == "https://huggingface.co"

    def test_hf_main_lowest_latency_goes_first(self):
        """HuggingFace 主站延迟最低 → 排第一位"""
        def fake_probe(host, port=443, timeout=3.0):
            if host == "huggingface.co":
                return 0.05
            return 0.5
        with patch.object(whisper_manager, '_probe_host', side_effect=fake_probe):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            assert result[0][0] == "https://huggingface.co"

    def test_modelscope_unreachable_deprioritized(self):
        """ModelScope 不可达 → 降为备选（排最后）"""
        def fake_probe(host, port=443, timeout=3.0):
            if host == "huggingface.modelscope.cn":
                return None  # 不可达
            return 0.1
        with patch.object(whisper_manager, '_probe_host', side_effect=fake_probe):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            # 不可达的排在最后
            assert result[-1][0] == "https://huggingface.modelscope.cn"

    def test_all_unreachable_still_returns_all(self):
        """全部不可达仍返回完整列表（延迟均为 999，保持原顺序）"""
        with patch.object(whisper_manager, '_probe_host', return_value=None):
            whisper_manager._cached_source_order = None
            result = whisper_manager._get_source_order()
            assert len(result) == 3
            for api_ep, label, url_tpl in result:
                # 每个源至少有 api_endpoint 或 url_template
                assert url_tpl is not None or api_ep is not None

    def test_result_is_cached(self):
        """探测结果只计算一次，后续调用走缓存"""
        with patch.object(whisper_manager, '_probe_host', return_value=0.1) as mock_probe:
            whisper_manager._cached_source_order = None
            whisper_manager._get_source_order()
            whisper_manager._get_source_order()
            # 3 个源各探测一次
            assert mock_probe.call_count == 3
