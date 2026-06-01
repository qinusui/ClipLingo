"""
测试 ASR 引擎注册表 + 工厂函数 + whisper_engine
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.asr.base import BaseASREngine
from core.asr import (
    ASR_ENGINE_REGISTRY, register_engine, get_available_engines, create_engine,
)


class TestEngineRegistry:
    """引擎注册表"""

    def test_default_engines_registered(self):
        """faster_whisper 和 bcut 应已注册"""
        # 导入模块后自动注册
        import core.asr.whisper_engine  # noqa: F401
        import core.asr.bcut_engine     # noqa: F401
        assert "faster_whisper" in ASR_ENGINE_REGISTRY
        assert "bcut" in ASR_ENGINE_REGISTRY

    def test_get_available_engines(self):
        """get_available_engines 应返回完整列表"""
        import core.asr.whisper_engine  # noqa
        import core.asr.bcut_engine     # noqa
        engines = get_available_engines()
        ids = [e["id"] for e in engines]
        assert "faster_whisper" in ids
        assert "bcut" in ids

    def test_create_whisper_engine(self):
        """create_engine("faster_whisper") 返回 FasterWhisperEngine"""
        import core.asr.whisper_engine  # noqa
        engine = create_engine("faster_whisper", model_name="tiny")
        assert engine.ENGINE_ID == "faster_whisper"
        assert engine.model_name == "tiny"

    def test_create_bcut_engine(self):
        """create_engine("bcut") 返回 BcutASREngine"""
        import core.asr.bcut_engine  # noqa
        engine = create_engine("bcut")
        assert engine.ENGINE_ID == "bcut"

    def test_create_unknown_engine_raises(self):
        """未知引擎 ID 应抛出 ValueError"""
        try:
            create_engine("nonexistent")
            assert False, "应抛出异常"
        except ValueError as e:
            assert "nonexistent" in str(e)

    def test_register_engine_decorator(self):
        """装饰器注册应正常工作"""
        @register_engine
        class FakeEngine(BaseASREngine):
            ENGINE_ID = "fake_test"
            ENGINE_NAME = "Fake Test Engine"
            def transcribe(self, audio_path, language=None, progress_callback=None):
                return []

        assert "fake_test" in ASR_ENGINE_REGISTRY
        # 清理
        del ASR_ENGINE_REGISTRY["fake_test"]


class TestWhisperEngine:
    """FasterWhisperEngine 转录"""

    def test_transcribe_delegates_to_whisper(self):
        """FasterWhisperEngine.transcribe() 应调用 faster_whisper"""
        import core.asr.whisper_engine  # noqa

        engine = create_engine("faster_whisper", model_name="tiny")

        mock_model = MagicMock()
        mock_seg = MagicMock()
        mock_seg.start = 0.0
        mock_seg.end = 2.0
        mock_seg.text = MagicMock()
        mock_seg.text.strip.return_value = "Hello world"
        mock_model.transcribe.return_value = iter([mock_seg]), MagicMock()

        with patch.object(engine, "_FasterWhisperEngine__load_model", return_value=mock_model, create=True):
            pass  # engine.transcribe() calls load_model internally

        # actually test through the real path with mocks
        with (
            patch("core.whisper_manager.load_model", return_value=mock_model),
        ):
            result = engine.transcribe("/fake/audio.mp3")
            assert len(result) == 1
            assert result[0]["text"] == "Hello world"

    def test_transcribe_raises_when_whisper_not_installed(self):
        """load_model 返回 None（whisper 不可用）应抛出 ClipLingoError(WHISPER_NOT_INSTALLED)"""
        import core.asr.whisper_engine  # noqa
        import pytest
        from errors import ClipLingoError, ErrorCode

        engine = create_engine("faster_whisper", model_name="tiny")
        with patch("core.whisper_manager.load_model", return_value=None):
            with pytest.raises(ClipLingoError) as exc_info:
                engine.transcribe("/fake/audio.mp3")
        assert exc_info.value.code == ErrorCode.WHISPER_NOT_INSTALLED

    def test_transcribe_wraps_runtime_errors(self):
        """转录过程异常应归类为 ClipLingoError(WHISPER_TRANSCRIBE_FAILED)"""
        import core.asr.whisper_engine  # noqa
        import pytest
        from errors import ClipLingoError, ErrorCode

        engine = create_engine("faster_whisper", model_name="tiny")

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("CUDA out of memory")

        with patch("core.whisper_manager.load_model", return_value=mock_model):
            with pytest.raises(ClipLingoError) as exc_info:
                engine.transcribe("/fake/audio.mp3")
        assert exc_info.value.code == ErrorCode.WHISPER_TRANSCRIBE_FAILED
