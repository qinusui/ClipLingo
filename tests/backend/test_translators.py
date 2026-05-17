"""
测试翻译服务注册表 + 工厂函数
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.translate.base import BaseTranslator
from core.translate import (
    TRANSLATOR_REGISTRY, register_translator, get_available_translators,
    create_translator, translate_batch,
)


class TestTranslatorRegistry:
    """翻译器注册表"""

    def test_default_translators_registered(self):
        """bing 和 google 应已注册"""
        import core.translate.bing    # noqa: F401
        import core.translate.google  # noqa: F401
        assert "bing" in TRANSLATOR_REGISTRY
        assert "google" in TRANSLATOR_REGISTRY

    def test_get_available_translators(self):
        """get_available_translators 应返回完整列表"""
        import core.translate.bing    # noqa
        import core.translate.google  # noqa
        services = get_available_translators()
        ids = [s["id"] for s in services]
        assert "bing" in ids
        assert "google" in ids

    def test_create_bing_translator(self):
        """create_translator("bing") 返回 BingTranslator"""
        import core.translate.bing  # noqa
        from core.translate.bing import BingTranslator
        with patch.object(BingTranslator, "_init_auth"):
            translator = create_translator("bing")
            assert translator.SERVICE_ID == "bing"

    def test_create_google_translator(self):
        """create_translator("google") 返回 GoogleTranslator"""
        import core.translate.google  # noqa
        translator = create_translator("google")
        assert translator.SERVICE_ID == "google"

    def test_create_unknown_translator_raises(self):
        """未知服务 ID 应抛出 ValueError"""
        try:
            create_translator("nonexistent")
            assert False, "应抛出异常"
        except ValueError as e:
            assert "nonexistent" in str(e)

    def test_register_translator_decorator(self):
        """装饰器注册应正常工作"""
        @register_translator
        class FakeTranslator(BaseTranslator):
            SERVICE_ID = "fake_translator"
            SERVICE_NAME = "Fake"
            def translate(self, texts, source_lang="auto", target_lang="zh"):
                return texts

        assert "fake_translator" in TRANSLATOR_REGISTRY
        del TRANSLATOR_REGISTRY["fake_translator"]


class TestTranslateBatch:
    """translate_batch 便捷函数"""

    def test_translate_batch_delegates(self):
        """translate_batch 应创建翻译器并调用 translate"""
        import core.translate.bing  # noqa
        from core.translate.bing import BingTranslator

        mock_translator = MagicMock()
        mock_translator.translate.return_value = ["你好", "世界"]

        with (
            patch.object(BingTranslator, "_init_auth"),
            patch("core.translate.create_translator", return_value=mock_translator) as mock_create,
        ):
            result = translate_batch(["Hello", "World"], "bing", "en", "zh")
            assert result == ["你好", "世界"]
            mock_create.assert_called_once_with("bing")
