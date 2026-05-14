"""
卡片样式生成器 API —— OpenAI 兼容的 AI 代理端点

前端发送对话消息，后端转发到 OpenAI 兼容 API（DeepSeek / OpenAI / Qwen 等），
API Key 可选择从前端传入或使用 .env 中的 DEEPSEEK_API_KEY。
"""

import logging
import os
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

router = APIRouter()


class StyleGeneratorMessage(BaseModel):
    role: str
    content: str


class StyleGeneratorRequest(BaseModel):
    messages: List[StyleGeneratorMessage]
    system_prompt: str = ""
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4000


@router.post("/generate")
async def generate(request: StyleGeneratorRequest):
    """调用 OpenAI 兼容 API 生成卡片模板"""
    api_key = request.api_key or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="未配置 API Key：请在模型设置中填写，或在 .env 中配置 DEEPSEEK_API_KEY")

    model = request.model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
    base_url = request.base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"

    messages = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    for m in request.messages:
        messages.append({"role": m.role, "content": m.content})

    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=request.max_tokens,
        )
        text = response.choices[0].message.content or ""
        return {"text": text, "model": model}
    except Exception as e:
        logger.error(f"Style generator API 调用失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI 调用失败: {e}")


@router.get("/config")
async def get_config():
    """返回当前默认配置（不暴露 API Key 完整值）"""
    key = os.getenv("DEEPSEEK_API_KEY") or ""
    masked = key[:4] + "****" + key[-4:] if len(key) > 8 else ""
    return {
        "has_default_key": bool(key),
        "masked_key": masked,
        "default_model": os.getenv("DEEPSEEK_MODEL") or "deepseek-chat",
        "default_base_url": os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    }
