"""
DeepLTranslator — DeepL 翻译
使用 DeepL REST API，需要 API Key（免费版可用），支持批量翻译

免费 API Key 申请: https://www.deepl.com/pro-api
"""
import hashlib
import logging
import os
import sys

import requests

from .base import BaseTranslator
from . import register_translator

logger = logging.getLogger(__name__)

# DeepL 免费版和付费版的 API 端点不同
# 免费版 Key 以 ":fx" 结尾
DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO_URL = "https://api.deepl.com/v2/translate"

HEADERS = {
    "User-Agent": "ClipLingo/1.0",
    "Content-Type": "application/x-www-form-urlencoded",
}

CACHE_EXPIRE = 86400 * 7  # 7 天

# DeepL 语言代码映射（ISO 639-1 → DeepL 格式）
# DeepL 要求大写，部分语言需要完整区域码
_DEEPL_LANG_MAP = {
    "zh": "ZH",
    "zh-cn": "ZH-HANS",
    "zh-tw": "ZH-HANT",
    "en": "EN-US",
    "en-gb": "EN-GB",
    "en-us": "EN-US",
    "pt": "PT-BR",
    "pt-br": "PT-BR",
    "pt-pt": "PT-PT",
    "ja": "JA",
    "ko": "KO",
    "fr": "FR",
    "de": "DE",
    "es": "ES",
    "it": "IT",
    "nl": "NL",
    "pl": "PL",
    "ru": "RU",
    "uk": "UK",
    "tr": "TR",
    "ar": "AR",
    "sv": "SV",
    "da": "DA",
    "nb": "NB",
    "no": "NB",
    "fi": "FI",
    "el": "EL",
    "cs": "CS",
    "ro": "RO",
    "hu": "HU",
    "id": "ID",
    "bg": "BG",
    "hi": "HI",
    "th": "TH",
}


def _normalize_lang(code: str) -> str:
    """将通用语言代码转换为 DeepL 格式"""
    if code == "auto":
        return ""
    return _DEEPL_LANG_MAP.get(code.lower(), code.upper())


def _get_api_url(api_key: str) -> str:
    """根据 API Key 格式自动选择免费版或付费版端点"""
    if api_key.endswith(":fx"):
        return DEEPL_FREE_URL
    return DEEPL_PRO_URL


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


def _cache_key(texts: list[str], source_lang: str, target_lang: str) -> str:
    content = "|".join(texts) + f"|{source_lang}|{target_lang}"
    return f"deepl:{hashlib.md5(content.encode()).hexdigest()}"


@register_translator
class DeepLTranslator(BaseTranslator):
    """DeepL 翻译

    使用 DeepL REST API 进行高质量翻译。
    需要 API Key（免费版每月 50 万字符）。
    支持批量翻译，一次请求可翻译多条文本。

    免费版申请: https://www.deepl.com/pro-api
    """

    SERVICE_ID = "deepl"
    SERVICE_NAME = "DeepL 翻译"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.session = requests.Session()

    def translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh",
    ) -> list[str]:
        if not texts:
            return []

        if not self.api_key:
            raise RuntimeError("DeepL 翻译需要 API Key，请在设置中配置")

        # 检查缓存
        cache = _get_diskcache()
        ck = _cache_key(texts, source_lang, target_lang)
        cached = cache.get(ck, default=None)
        if cached is not None:
            logger.debug("DeepL 翻译命中缓存")
            return cached

        # 构建请求参数（DeepL 使用 form-urlencoded，text 参数可重复）
        api_url = _get_api_url(self.api_key)
        target = _normalize_lang(target_lang)

        data: list[tuple[str, str]] = [
            ("auth_key", self.api_key),
            ("target_lang", target),
        ]

        source = _normalize_lang(source_lang)
        if source:
            data.append(("source_lang", source))

        # 每条文本限 5000 字符
        for t in texts:
            data.append(("text", t[:5000]))

        try:
            resp = self.session.post(
                api_url,
                data=data,
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            result_data = resp.json()
            result = [t["text"] for t in result_data.get("translations", [])]
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 403:
                raise RuntimeError("DeepL API Key 无效或已过期")
            elif status == 456:
                raise RuntimeError("DeepL API 配额已用尽（免费版每月 50 万字符）")
            raise RuntimeError(f"DeepL 翻译请求失败: {e}")
        except Exception as e:
            logger.error(f"DeepL 翻译请求失败: {e}")
            raise RuntimeError(f"DeepL 翻译请求失败: {e}")

        # 缓存结果
        cache.set(ck, result, expire=CACHE_EXPIRE)
        return result

    @classmethod
    def is_available(cls) -> bool:
        # DeepL 服务本身可用，但需要用户提供 API Key
        return True
