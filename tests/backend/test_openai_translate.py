"""
测试 OpenAITranslator — AI 翻译（OpenAI 兼容）
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestOpenAILangDisplay:
    """语言显示名称测试"""

    def test_known_lang(self):
        from core.translate.openai_translate import _lang_display_name
        assert _lang_display_name("en") == "English"
        assert _lang_display_name("zh") == "中文"
        assert _lang_display_name("ja") == "日本語"

    def test_unknown_lang_returns_code(self):
        from core.translate.openai_translate import _lang_display_name
        assert _lang_display_name("xx") == "xx"

    def test_auto(self):
        from core.translate.openai_translate import _lang_display_name
        assert _lang_display_name("auto") == "原文语言"


class TestOpenAITranslate:
    """翻译测试"""

    def test_batch_translate(self):
        """批量翻译应调用 OpenAI API 并解析 JSON 结果"""
        from core.translate.openai_translate import OpenAITranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "translations": ["你好", "世界"]
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with (
            patch("openai.OpenAI", return_value=mock_client),
            patch("core.translate.openai_translate._get_diskcache", return_value=mock_cache),
        ):
            translator = OpenAITranslator(
                api_key="test_key",
                api_base="https://api.test.com",
                model_name="test-model",
            )
            result = translator.translate(["Hello", "World"], "en", "zh")

            assert result == ["你好", "世界"]
            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == "test-model"
            assert call_kwargs["temperature"] == 0.3

    def test_no_api_key_raises(self):
        """无 API Key 应抛出 RuntimeError"""
        from core.translate.openai_translate import OpenAITranslator

        translator = OpenAITranslator(api_key="")
        try:
            translator.translate(["Hello"], "en", "zh")
            assert False, "应抛出异常"
        except RuntimeError as e:
            assert "API Key" in str(e)

    def test_empty_input(self):
        """空列表应直接返回"""
        from core.translate.openai_translate import OpenAITranslator

        translator = OpenAITranslator(api_key="test_key")
        assert translator.translate([], "en", "zh") == []

    def test_cache_hit(self):
        """缓存命中时不应调用 OpenAI API"""
        from core.translate.openai_translate import OpenAITranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = ["缓存结果"]

        with patch("core.translate.openai_translate._get_diskcache", return_value=mock_cache):
            translator = OpenAITranslator(api_key="test_key")
            result = translator.translate(["Hello"], "en", "zh")

            assert result == ["缓存结果"]

    def test_result_padding(self):
        """翻译结果少于输入时应填充空字符串"""
        from core.translate.openai_translate import OpenAITranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # 只返回 1 条结果，但输入有 3 条
        mock_response.choices[0].message.content = json.dumps({
            "translations": ["你好"]
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with (
            patch("openai.OpenAI", return_value=mock_client),
            patch("core.translate.openai_translate._get_diskcache", return_value=mock_cache),
        ):
            translator = OpenAITranslator(api_key="test_key")
            result = translator.translate(["Hello", "World", "Test"], "en", "zh")

            assert len(result) == 3
            assert result[0] == "你好"
            assert result[1] == ""
            assert result[2] == ""

    def test_invalid_json_raises(self):
        """AI 返回非 JSON 内容应抛出错误"""
        from core.translate.openai_translate import OpenAITranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "这不是 JSON"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with (
            patch("openai.OpenAI", return_value=mock_client),
            patch("core.translate.openai_translate._get_diskcache", return_value=mock_cache),
        ):
            translator = OpenAITranslator(api_key="test_key")
            try:
                translator.translate(["Hello"], "en", "zh")
                assert False, "应抛出异常"
            except RuntimeError as e:
                assert "格式错误" in str(e)

    def test_text_truncation(self):
        """超过 3000 字符的文本应截断"""
        from core.translate.openai_translate import OpenAITranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({"translations": ["OK"]})

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with (
            patch("openai.OpenAI", return_value=mock_client),
            patch("core.translate.openai_translate._get_diskcache", return_value=mock_cache),
        ):
            translator = OpenAITranslator(api_key="test_key")
            long_text = "A" * 5000
            translator.translate([long_text], "en", "zh")

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            user_content = call_kwargs["messages"][1]["content"]
            parsed = json.loads(user_content)
            assert len(parsed[0]) == 3000

    def test_default_params(self):
        """默认参数应正确设置"""
        from core.translate.openai_translate import OpenAITranslator

        translator = OpenAITranslator(api_key="key")
        assert translator.api_base == "https://api.deepseek.com"
        assert translator.model_name == "deepseek-chat"


class TestOpenAIRegistration:
    """注册表测试"""

    def test_registered(self):
        """OpenAI 翻译应已注册到翻译器注册表"""
        import core.translate.openai_translate  # noqa
        from core.translate import TRANSLATOR_REGISTRY
        assert "openai" in TRANSLATOR_REGISTRY

    def test_service_id(self):
        from core.translate.openai_translate import OpenAITranslator
        assert OpenAITranslator.SERVICE_ID == "openai"

    def test_is_available(self):
        from core.translate.openai_translate import OpenAITranslator
        assert OpenAITranslator.is_available() is True
