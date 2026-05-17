"""
BingTranslator — 微软必应翻译
使用 Microsoft Edge 翻译 API，免费、无需 API Key、支持批量翻译

Portions adapted from VideoCaptioner (MIT License)
Copyright (c) 2024 weifangma
https://github.com/weifangma/VideoCaptioner
"""
import hashlib
import json
import logging
import os
import sys
import time

import requests

from .base import BaseTranslator
from . import register_translator

logger = logging.getLogger(__name__)

BING_AUTH_URL = "https://edge.microsoft.com/translate/auth"
BING_TRANSLATE_URL = "https://api-edge.cognitive.microsofttranslator.com/translate"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
    ),
}

CACHE_EXPIRE = 86400 * 7  # 7 天


def _get_cache_dir() -> str:
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'ClipLingo', 'cache', 'translate')
    else:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cache', 'translate')


class _NoOpCache:
    """占位缓存：diskcache 不可用时，get/set 均为空操作"""
    def get(self, key, default=None): return default
    def set(self, key, value, **kw): pass
    def _sql(self, *args, **kw): return type('_FakeResult', (), {'fetchall': lambda: []})()


def _get_diskcache():
    try:
        import diskcache
    except ImportError:
        return _NoOpCache()
    cache_dir = _get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    return diskcache.Cache(cache_dir)


def _cache_key(texts: list[str], source_lang: str, target_lang: str) -> str:
    content = "|".join(texts) + f"|{source_lang}|{target_lang}"
    return f"bing:{hashlib.md5(content.encode()).hexdigest()}"


@register_translator
class BingTranslator(BaseTranslator):
    """微软翻译（Bing）

    使用 Microsoft Edge 浏览器的免费翻译接口，
    自动获取 Bearer Token，无需 API Key。
    支持批量翻译，一次请求可翻译多条文本。
    """

    SERVICE_ID = "bing"
    SERVICE_NAME = "微软翻译（Bing）"

    def __init__(self):
        self.session = requests.Session()
        self.auth_token: str = ""
        self._init_auth()

    def _init_auth(self):
        """获取 Bearer Token"""
        try:
            resp = self.session.get(BING_AUTH_URL, timeout=20, headers=HEADERS)
            resp.raise_for_status()
            self.auth_token = resp.text
        except Exception as e:
            logger.error(f"Bing 翻译认证失败: {e}")
            raise RuntimeError(f"Bing 翻译认证失败: {e}")

    def translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh",
    ) -> list[str]:
        if not texts:
            return []

        # 检查缓存
        cache = _get_diskcache()
        ck = _cache_key(texts, source_lang, target_lang)
        cached = cache.get(ck, default=None)
        if cached is not None:
            logger.debug("Bing 翻译命中缓存")
            return cached

        # 准备批量请求（每条限 5000 字符）
        payload = [{"Text": t[:5000]} for t in texts]

        params = {
            "to": target_lang,
            "api-version": "3.0",
            "includeSentenceLength": "true",
        }
        headers = {**HEADERS, "authorization": f"Bearer {self.auth_token}"}

        try:
            resp = self.session.post(
                BING_TRANSLATE_URL,
                params=params,
                headers=headers,
                json=payload,
                timeout=30,
            )

            # Token 过期则重新获取并重试一次
            if resp.status_code in (401, 403):
                logger.info("Bing Token 过期，重新获取...")
                self._init_auth()
                headers["authorization"] = f"Bearer {self.auth_token}"
                resp = self.session.post(
                    BING_TRANSLATE_URL,
                    params=params,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

            resp.raise_for_status()
            result = [t["translations"][0]["text"] for t in resp.json()]
        except Exception as e:
            logger.error(f"Bing 翻译请求失败: {e}")
            raise RuntimeError(f"Bing 翻译请求失败: {e}")

        # 缓存结果
        cache.set(ck, result, expire=CACHE_EXPIRE)
        return result

    @classmethod
    def is_available(cls) -> bool:
        return True
