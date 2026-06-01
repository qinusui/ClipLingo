"""
测试 DeepLTranslator — DeepL 翻译
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDeepLLangMapping:
    """语言代码映射测试"""

    def test_normalize_zh(self):
        from core.translate.deepl import _normalize_lang
        assert _normalize_lang("zh") == "ZH"

    def test_normalize_en(self):
        from core.translate.deepl import _normalize_lang
        assert _normalize_lang("en") == "EN-US"

    def test_normalize_auto(self):
        from core.translate.deepl import _normalize_lang
        assert _normalize_lang("auto") == ""

    def test_normalize_unknown_uppercases(self):
        from core.translate.deepl import _normalize_lang
        assert _normalize_lang("xx") == "XX"

    def test_normalize_case_insensitive(self):
        from core.translate.deepl import _normalize_lang
        assert _normalize_lang("JA") == "JA"
        assert _normalize_lang("ja") == "JA"


class TestDeepLApiUrl:
    """API 端点选择测试"""

    def test_free_key_uses_free_url(self):
        from core.translate.deepl import _get_api_url, DEEPL_FREE_URL
        assert _get_api_url("abc123:fx") == DEEPL_FREE_URL

    def test_pro_key_uses_pro_url(self):
        from core.translate.deepl import _get_api_url, DEEPL_PRO_URL
        assert _get_api_url("abc123") == DEEPL_PRO_URL


class TestDeepLTranslate:
    """翻译测试"""

    def test_batch_translate(self):
        """批量翻译应发送正确的请求"""
        from core.translate.deepl import DeepLTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "translations": [
                {"text": "你好"},
                {"text": "世界"},
            ]
        }

        session = MagicMock()
        session.post.return_value = mock_resp

        with (
            patch.object(DeepLTranslator, "__init__", lambda self, api_key="": setattr(self, "api_key", "test_key") or setattr(self, "session", session)),
            patch("core.translate.deepl._get_diskcache", return_value=mock_cache),
        ):
            translator = DeepLTranslator(api_key="test_key")
            result = translator.translate(["Hello", "World"], "en", "zh")

            assert result == ["你好", "世界"]
            call_args = session.post.call_args
            data = call_args[1]["data"]
            # 验证 target_lang
            assert ("target_lang", "ZH") in data
            # 验证 source_lang
            assert ("source_lang", "EN-US") in data

    def test_no_api_key_raises(self):
        """无 API Key 应抛出 ClipLingoError(API_KEY_MISSING)"""
        from core.translate.deepl import DeepLTranslator
        from errors import ClipLingoError, ErrorCode

        translator = DeepLTranslator(api_key="")
        try:
            translator.translate(["Hello"], "en", "zh")
            assert False, "应抛出异常"
        except ClipLingoError as e:
            assert e.code == ErrorCode.API_KEY_MISSING
            assert "API Key" in str(e)

    def test_empty_input(self):
        """空列表应直接返回"""
        from core.translate.deepl import DeepLTranslator

        translator = DeepLTranslator(api_key="test_key")
        assert translator.translate([], "en", "zh") == []

    def test_cache_hit(self):
        """缓存命中时不应发起网络请求"""
        from core.translate.deepl import DeepLTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = ["缓存结果"]

        session = MagicMock()

        translator = DeepLTranslator.__new__(DeepLTranslator)
        translator.api_key = "test_key"
        translator.session = session

        with patch("core.translate.deepl._get_diskcache", return_value=mock_cache):
            result = translator.translate(["Hello"], "en", "zh")

            assert result == ["缓存结果"]
            session.post.assert_not_called()

    def test_quota_exceeded_raises(self):
        """456 状态码应抛出配额用尽错误 ClipLingoError(API_QUOTA_EXCEEDED)"""
        import requests
        from core.translate.deepl import DeepLTranslator
        from errors import ClipLingoError, ErrorCode

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 456
        http_error = requests.exceptions.HTTPError(response=mock_resp)

        session = MagicMock()
        session.post.side_effect = http_error

        translator = DeepLTranslator.__new__(DeepLTranslator)
        translator.api_key = "test_key"
        translator.session = session

        with patch("core.translate.deepl._get_diskcache", return_value=mock_cache):
            try:
                translator.translate(["Hello"], "en", "zh")
                assert False, "应抛出异常"
            except ClipLingoError as e:
                assert e.code == ErrorCode.API_QUOTA_EXCEEDED
                assert "配额" in str(e)

    def test_invalid_key_raises(self):
        """403 状态码应抛出 Key 无效错误 ClipLingoError(TRANSLATE_AUTH_FAILED)"""
        import requests
        from core.translate.deepl import DeepLTranslator
        from errors import ClipLingoError, ErrorCode

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        http_error = requests.exceptions.HTTPError(response=mock_resp)

        session = MagicMock()
        session.post.side_effect = http_error

        translator = DeepLTranslator.__new__(DeepLTranslator)
        translator.api_key = "bad_key"
        translator.session = session

        with patch("core.translate.deepl._get_diskcache", return_value=mock_cache):
            try:
                translator.translate(["Hello"], "en", "zh")
                assert False, "应抛出异常"
            except ClipLingoError as e:
                assert e.code == ErrorCode.TRANSLATE_AUTH_FAILED
                assert "无效" in str(e)


class TestDeepLRegistration:
    """注册表测试"""

    def test_registered(self):
        """DeepL 应已注册到翻译器注册表"""
        import core.translate.deepl  # noqa
        from core.translate import TRANSLATOR_REGISTRY
        assert "deepl" in TRANSLATOR_REGISTRY

    def test_service_id(self):
        from core.translate.deepl import DeepLTranslator
        assert DeepLTranslator.SERVICE_ID == "deepl"

    def test_is_available(self):
        from core.translate.deepl import DeepLTranslator
        assert DeepLTranslator.is_available() is True
