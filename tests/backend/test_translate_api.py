"""
translate API 端点测试
覆盖：获取翻译服务列表、批量翻译、参数校验、错误处理
"""

import sys
from pathlib import Path

# 设置路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(TEST_ROOT / "backend"))

import pytest
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from api import translate as translate_module

app = FastAPI()
app.include_router(translate_module.router, prefix="/api/translate")


@pytest.fixture
def client():
    return TestClient(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /services
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetServices:
    """获取翻译服务列表"""

    @patch("core.translate.get_available_translators")
    def test_list_services(self, mock_get, client):
        """列出可用翻译服务"""
        mock_get.return_value = [
            {"id": "bing", "name": "Bing", "available": True},
            {"id": "google", "name": "Google", "available": True},
        ]

        resp = client.get("/api/translate/services")

        assert resp.status_code == 200
        services = resp.json()["services"]
        assert len(services) >= 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /batch
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTranslateBatch:
    """批量翻译"""

    def test_empty_texts(self, client):
        """空文本列表应返回空结果"""
        resp = client.post("/api/translate/batch", json={
            "texts": [],
            "service": "bing",
        })

        assert resp.status_code == 200
        assert resp.json()["translations"] == []

    @patch("core.translate.create_translator")
    def test_translate_bing(self, mock_create, client):
        """Bing 翻译"""
        mock_translator = Mock()
        mock_create.return_value = mock_translator
        mock_translator.translate.return_value = ["你好", "世界"]

        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello", "World"],
            "service": "bing",
            "source_lang": "en",
            "target_lang": "zh",
        })

        assert resp.status_code == 200
        assert resp.json()["translations"] == ["你好", "世界"]

    @patch("core.translate.create_translator")
    def test_translate_google(self, mock_create, client):
        """Google 翻译"""
        mock_translator = Mock()
        mock_create.return_value = mock_translator
        mock_translator.translate.return_value = ["Bonjour"]

        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "google",
        })

        assert resp.status_code == 200
        assert resp.json()["translations"] == ["Bonjour"]

    def test_translate_deepl_missing_api_key(self, client):
        """DeepL 翻译缺少 API Key"""
        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "deepl",
        })

        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]

    @patch("core.translate.create_translator")
    def test_translate_deepl_with_key(self, mock_create, client):
        """DeepL 翻译带 API Key"""
        mock_translator = Mock()
        mock_create.return_value = mock_translator
        mock_translator.translate.return_value = ["Hallo"]

        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "deepl",
            "api_key": "test-deepl-key",
        })

        assert resp.status_code == 200

    def test_translate_openai_missing_api_key(self, client):
        """OpenAI 翻译缺少 API Key"""
        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "openai",
        })

        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]

    def test_unknown_service(self, client):
        """未知翻译服务"""
        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "unknown_service-xyz",
        })

        assert resp.status_code == 400
        assert "未知" in resp.json()["detail"]

    @patch("core.translate.create_translator")
    def test_translate_exception(self, mock_create, client):
        """翻译异常处理"""
        mock_translator = Mock()
        mock_create.return_value = mock_translator
        mock_translator.translate.side_effect = Exception("Network error")

        resp = client.post("/api/translate/batch", json={
            "texts": ["Hello"],
            "service": "bing",
        })

        assert resp.status_code == 500
        assert "翻译失败" in resp.json()["detail"]

    @patch("core.translate.create_translator")
    def test_translate_with_all_params(self, mock_create, client):
        """带所有参数的翻译"""
        mock_translator = Mock()
        mock_create.return_value = mock_translator
        mock_translator.translate.return_value = ["译文"]

        resp = client.post("/api/translate/batch", json={
            "texts": ["Source"],
            "service": "openai",
            "source_lang": "en",
            "target_lang": "ja",
            "api_key": "test-key",
            "api_base": "https://custom.api.com",
            "model_name": "gpt-4",
        })

        assert resp.status_code == 200
        mock_translator.translate.assert_called_once_with(
            ["Source"],
            source_lang="en",
            target_lang="ja",
        )
