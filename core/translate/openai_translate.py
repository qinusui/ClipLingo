"""
OpenAITranslator — 基于 OpenAI 兼容 API 的翻译
使用用户已配置的 AI 模型（DeepSeek / OpenAI / Ollama 等），翻译质量高

复用前端已配置的 api_key / api_base / model_name，无需额外配置
"""
import hashlib
import json
import logging
import os
import sys

from .base import BaseTranslator
from . import register_translator

logger = logging.getLogger(__name__)

CACHE_EXPIRE = 86400 * 7  # 7 天

_SYSTEM_PROMPT = """\
你是一个专业翻译。将用户提供的文本列表从 {source} 翻译为 {target}。

要求：
- 返回 JSON 格式：{{"translations": ["译文1", "译文2", ...]}}
- 保持与输入等长的翻译结果
- 翻译自然流畅，符合目标语言习惯
- 保留原文的语气和风格
- 如遇专有名词，可保留原文或音译
- 只返回 JSON，不要有其他内容"""


def _get_diskcache():
    try:
        import diskcache
    except ImportError:
        from .bing import _NoOpCache
        return _NoOpCache()
    from .bing import _get_cache_dir
    cache_dir = _get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    return diskcache.Cache(cache_dir)


def _cache_key(texts: list[str], source_lang: str, target_lang: str, model: str) -> str:
    content = "|".join(texts) + f"|{source_lang}|{target_lang}|{model}"
    return f"openai_mt:{hashlib.md5(content.encode()).hexdigest()}"


def _lang_display_name(code: str) -> str:
    """将语言代码转为可读名称"""
    _NAMES = {
        "en": "English", "zh": "中文", "ja": "日本語", "ko": "한국어",
        "fr": "Français", "de": "Deutsch", "es": "Español", "it": "Italiano",
        "pt": "Português", "ru": "Русский", "ar": "العربية", "hi": "हिन्दी",
        "th": "ไทย", "vi": "Tiếng Việt", "nl": "Nederlands", "pl": "Polski",
        "tr": "Türkçe", "sv": "Svenska", "auto": "原文语言",
    }
    return _NAMES.get(code.lower(), code)


@register_translator
class OpenAITranslator(BaseTranslator):
    """AI 翻译（OpenAI 兼容）

    使用用户已配置的 OpenAI 兼容 API（DeepSeek / OpenAI / Ollama 等）
    进行高质量翻译。复用前端 AI 配置，无需额外设置。
    """

    SERVICE_ID = "openai"
    SERVICE_NAME = "AI 翻译（OpenAI 兼容）"

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.deepseek.com",
        model_name: str = "deepseek-chat",
    ):
        self.api_key = api_key
        self.api_base = api_base or "https://api.deepseek.com"
        self.model_name = model_name or "deepseek-chat"

    def translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh",
    ) -> list[str]:
        if not texts:
            return []

        if not self.api_key:
            raise RuntimeError("AI 翻译需要 API Key，请在设置中配置")

        # 检查缓存
        cache = _get_diskcache()
        ck = _cache_key(texts, source_lang, target_lang, self.model_name)
        cached = cache.get(ck, default=None)
        if cached is not None:
            logger.debug("AI 翻译命中缓存")
            return cached

        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.api_base)

        source_name = _lang_display_name(source_lang)
        target_name = _lang_display_name(target_lang)
        system_prompt = _SYSTEM_PROMPT.format(source=source_name, target=target_name)

        # 截断超长文本
        truncated = [t[:3000] for t in texts]
        user_content = json.dumps(truncated, ensure_ascii=False)

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                timeout=60.0,
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            result = parsed.get("translations", [])

            # 确保结果长度与输入一致
            while len(result) < len(texts):
                result.append("")
            result = result[:len(texts)]
        except json.JSONDecodeError:
            logger.error(f"AI 翻译返回非 JSON 内容: {content[:200] if content else 'empty'}")
            raise RuntimeError("AI 翻译返回格式错误，请重试")
        except Exception as e:
            logger.error(f"AI 翻译请求失败: {e}")
            raise RuntimeError(f"AI 翻译请求失败: {e}")

        # 缓存结果
        cache.set(ck, result, expire=CACHE_EXPIRE)
        return result

    @classmethod
    def is_available(cls) -> bool:
        return True
