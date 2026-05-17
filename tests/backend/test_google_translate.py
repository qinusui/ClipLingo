"""
测试 GoogleTranslator — 谷歌翻译
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestGoogleTranslate:
    """谷歌翻译测试"""

    def test_extract_translation_from_html(self):
        """从 Google 移动端 HTML 中提取译文"""
        from core.translate.google import GoogleTranslator

        html_resp = (
            '<html><body>'
            '<div class="result-container">你好世界</div>'
            '</body></html>'
        )

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html_resp
        session.get.return_value = resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["Hello world"], "en", "zh")
            assert result == ["你好世界"]

    def test_extract_with_html_entities(self):
        """HTML 实体应被解码"""
        from core.translate.google import GoogleTranslator

        html_resp = '<div class="t0">It&#39;s &quot;great&quot; &amp; more</div>'

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html_resp
        session.get.return_value = resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["test"], "en", "zh")
            assert result == ['It\'s "great" & more']

    def test_http_400_keeps_original(self):
        """400 错误时保留原文"""
        from core.translate.google import GoogleTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        session.get.return_value = resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["Hello"], "en", "zh")
            assert result == ["Hello"]  # 保留原文

    def test_text_truncation(self):
        """超过 5000 字符应截断"""
        from core.translate.google import GoogleTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        captured_params = []

        def capture(url, **kwargs):
            captured_params.append(kwargs.get("params", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '<div class="result-container">OK</div>'
            return resp

        session.get.side_effect = capture

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            long_text = "B" * 6000
            translator.translate([long_text], "en", "zh")
            assert len(captured_params[0]["q"]) == 5000

    def test_cache_hit(self):
        """缓存命中时不应发起网络请求"""
        from core.translate.google import GoogleTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = "缓存翻译"

        session = MagicMock()

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["Hello"], "en", "zh")
            assert result == ["缓存翻译"]
            session.get.assert_not_called()

    def test_empty_input(self):
        """空列表应直接返回空列表"""
        from core.translate.google import GoogleTranslator

        translator = GoogleTranslator()
        result = translator.translate([], "en", "zh")
        assert result == []

    def test_parse_failure_keeps_original(self):
        """HTML 解析失败时保留原文"""
        from core.translate.google import GoogleTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "<html>no translation here</html>"
        session.get.return_value = resp

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["Hello"], "en", "zh")
            assert result == ["Hello"]

    def test_network_error_keeps_original(self):
        """网络错误时保留原文，不抛异常"""
        from core.translate.google import GoogleTranslator

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        session = MagicMock()
        session.get.side_effect = Exception("Connection timeout")

        with (
            patch("requests.Session", return_value=session),
            patch("core.translate.google._get_diskcache", return_value=mock_cache),
        ):
            translator = GoogleTranslator()
            result = translator.translate(["Hello"], "en", "zh")
            assert result == ["Hello"]  # 网络错误时保留原文
