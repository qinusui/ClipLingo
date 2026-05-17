"""
测试 BingTranslator — 微软翻译
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestBingAuth:
    """认证测试"""

    def test_init_auth_fetches_token(self):
        """初始化时应从 edge.microsoft.com 获取 token"""
        from core.translate.bing import BingTranslator

        mock_resp = MagicMock()
        mock_resp.text = "fake_bearer_token_123"

        session = MagicMock()
        session.get.return_value = mock_resp

        with patch("requests.Session", return_value=session):
            translator = BingTranslator()
            assert translator.auth_token == "fake_bearer_token_123"
            session.get.assert_called_once()
            assert "edge.microsoft.com" in session.get.call_args[0][0]

    def test_auth_failure_raises(self):
        """认证失败应抛出 RuntimeError"""
        from core.translate.bing import BingTranslator

        session = MagicMock()
        session.get.side_effect = Exception("Connection refused")

        with patch("requests.Session", return_value=session):
            try:
                BingTranslator()
                assert False, "应抛出异常"
            except RuntimeError as e:
                assert "认证失败" in str(e)


class TestBingTranslate:
    """翻译测试"""

    def test_batch_translate(self):
        """批量翻译应发送正确的 JSON payload"""
        from core.translate.bing import BingTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None  # 无缓存

        translate_resp = MagicMock()
        translate_resp.json.return_value = [
            {"translations": [{"text": "你好"}]},
            {"translations": [{"text": "世界"}]},
        ]

        session = MagicMock()
        session.get.return_value = MagicMock(text="fake_token")
        session.post.return_value = translate_resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.bing._get_diskcache", return_value=mock_cache),
        ):
            translator = BingTranslator()
            result = translator.translate(["Hello", "World"], "en", "zh")

            assert result == ["你好", "世界"]
            # 验证 POST body
            call_args = session.post.call_args
            payload = call_args[1]["json"]
            assert payload == [{"Text": "Hello"}, {"Text": "World"}]
            assert call_args[1]["params"]["to"] == "zh"
            assert call_args[1]["params"]["api-version"] == "3.0"

    def test_token_refresh_on_401(self):
        """401/403 时应重新获取 token 并重试"""
        from core.translate.bing import BingTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        # 第一次 post 返回 401，第二次成功
        fail_resp = MagicMock()
        fail_resp.status_code = 401
        success_resp = MagicMock()
        success_resp.json.return_value = [{"translations": [{"text": "你好"}]}]

        session = MagicMock()
        # get 返回两次（初始 + 刷新）
        session.get.side_effect = [
            MagicMock(text="old_token"),
            MagicMock(text="new_token"),
        ]
        session.post.side_effect = [fail_resp, success_resp]

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.bing._get_diskcache", return_value=mock_cache),
        ):
            translator = BingTranslator()
            result = translator.translate(["Hello"], "en", "zh")
            assert result == ["你好"]
            # 确认调用了两次 POST
            assert session.post.call_count == 2
            # 确认重新获取了 token
            assert session.get.call_count == 2

    def test_cache_hit(self):
        """缓存命中时不应发起网络请求"""
        from core.translate.bing import BingTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = ["缓存结果"]

        session = MagicMock()

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.bing._get_diskcache", return_value=mock_cache),
        ):
            translator = BingTranslator()
            # 重置 session mock 以确保认证 GET 已经发生过
            session.reset_mock()
            result = translator.translate(["Hello"], "en", "zh")

            assert result == ["缓存结果"]
            # 缓存命中后不应有 POST 请求
            session.post.assert_not_called()

    def test_empty_input(self):
        """空列表应直接返回空列表"""
        from core.translate.bing import BingTranslator

        with patch.object(BingTranslator, "_init_auth"):
            translator = BingTranslator()
            result = translator.translate([], "en", "zh")
            assert result == []

    def test_text_truncation(self):
        """超过 5000 字符的文本应截断"""
        from core.translate.bing import BingTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        success_resp = MagicMock()
        success_resp.json.return_value = [{"translations": [{"text": "OK"}]}]

        session = MagicMock()
        session.get.return_value = MagicMock(text="token")
        session.post.return_value = success_resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.bing._get_diskcache", return_value=mock_cache),
        ):
            translator = BingTranslator()
            long_text = "A" * 6000
            translator.translate([long_text], "en", "zh")

            payload = session.post.call_args[1]["json"]
            assert len(payload[0]["Text"]) == 5000
