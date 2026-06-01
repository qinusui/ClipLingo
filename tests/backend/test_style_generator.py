"""
style_generator API 端点测试
覆盖：AI 样式生成、配置获取、参数校验
"""

import sys
from pathlib import Path

# 设置路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(TEST_ROOT / "backend"))

import pytest
from unittest.mock import patch, Mock, AsyncMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from api import style_generator as style_module

app = FastAPI()
app.include_router(style_module.router, prefix="/api/style-generator")


@pytest.fixture
def client():
    return TestClient(app)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /generate
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGenerate:
    """AI 样式生成端点"""

    def test_missing_api_key(self, client, monkeypatch):
        """缺少 API Key 应返回 400"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "生成样式"}],
        })

        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]

    @patch("api.style_generator.AsyncOpenAI")
    def test_generate_normal(self, mock_openai_cls, client):
        """正常生成样式"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = ".card { color: red; }"

        # AsyncMock for async method
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "生成卡片样式"}],
            "api_key": "test-key",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "model" in data

    @patch("api.style_generator.AsyncOpenAI")
    def test_generate_with_system_prompt(self, mock_openai_cls, client):
        """带系统提示词生成"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "CSS output"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "生成"}],
            "system_prompt": "你是样式生成专家",
            "api_key": "test-key",
        })

        assert resp.status_code == 200

    @patch("api.style_generator.AsyncOpenAI")
    def test_generate_custom_model(self, mock_openai_cls, client):
        """使用自定义模型"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "result"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "test"}],
            "api_key": "key",
            "model": "gpt-4",
        })

        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4"

    @patch("api.style_generator.AsyncOpenAI")
    def test_generate_api_error(self, mock_openai_cls, client):
        """API 调用失败"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "test"}],
            "api_key": "key",
        })

        assert resp.status_code == 500
        assert "AI 调用失败" in resp.json()["detail"]

    @patch("api.style_generator.AsyncOpenAI")
    def test_generate_with_base_url(self, mock_openai_cls, client):
        """自定义 base_url"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = "css"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        resp = client.post("/api/style-generator/generate", json={
            "messages": [{"role": "user", "content": "test"}],
            "api_key": "key",
            "base_url": "https://custom.api.com",
        })

        assert resp.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetConfig:
    """获取配置"""

    def test_config_no_key(self, client, monkeypatch):
        """无 API Key 配置"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

        resp = client.get("/api/style-generator/config")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_default_key"] is False
        assert data["default_model"] == "deepseek-chat"

    def test_config_with_key(self, client, monkeypatch):
        """有 API Key 配置（应脱敏）"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-1234567890abcdef")
        monkeypatch.setenv("DEEPSEEK_MODEL", "gpt-4")

        resp = client.get("/api/style-generator/config")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_default_key"] is True
        assert "****" in data["masked_key"]
        assert data["default_model"] == "gpt-4"

    def test_config_short_key(self, client, monkeypatch):
        """API Key 过短时应返回空掩码"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "short")

        resp = client.get("/api/style-generator/config")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_default_key"] is True
        assert data["masked_key"] == ""  # 长度 < 8 时为空
