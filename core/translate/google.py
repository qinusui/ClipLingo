"""
GoogleTranslator — 谷歌翻译（备用）
使用 Google 移动端网页翻译，免费、无需 API Key

Portions adapted from VideoCaptioner (MIT License)
Copyright (c) 2024 weifangma
https://github.com/weifangma/VideoCaptioner
"""
import hashlib
import html as html_mod
import logging
import os
import re
import sys

import requests

from .base import BaseTranslator
from . import register_translator

logger = logging.getLogger(__name__)

GOOGLE_TRANSLATE_URL = "https://translate.google.com/m"

HEADERS = {
    "User-Agent": (
        "Mozilla/4.0 (compatible;MSIE 6.0;Windows NT 5.1;SV1;"
        ".NET CLR 1.1.4322;.NET CLR 2.0.50727;.NET CLR 3.0.04506.30)"
    ),
}

CACHE_EXPIRE = 86400 * 7  # 7 天


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


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    return f"google:{hashlib.md5(f'{text}|{source_lang}|{target_lang}'.encode()).hexdigest()}"


@register_translator
class GoogleTranslator(BaseTranslator):
    """谷歌翻译（备用）

    使用 Google 移动端网页翻译接口，通过 HTML 抓取获取译文。
    逐条翻译（不支持批量），速度较慢，建议作为 Bing 的备用方案。
    """

    SERVICE_ID = "google"
    SERVICE_NAME = "谷歌翻译（备用）"

    def __init__(self):
        self.session = requests.Session()

    def translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh",
    ) -> list[str]:
        if not texts:
            return []

        cache = _get_diskcache()
        results = []

        for text in texts:
            ck = _cache_key(text, source_lang, target_lang)
            cached = cache.get(ck, default=None)
            if cached is not None:
                results.append(cached)
                continue

            try:
                translated = self._translate_one(text, source_lang, target_lang)
                cache.set(ck, translated, expire=CACHE_EXPIRE)
                results.append(translated)
            except Exception as e:
                logger.warning(f"Google 翻译失败，保留原文: {str(e)[:100]}")
                results.append(text)  # 失败时保留原文

        return results

    def _translate_one(self, text: str, source_lang: str, target_lang: str) -> str:
        """翻译单条文本"""
        resp = self.session.get(
            GOOGLE_TRANSLATE_URL,
            params={
                "tl": target_lang,
                "sl": source_lang,
                "q": text[:5000],
            },
            headers=HEADERS,
            timeout=20,
        )

        if resp.status_code == 400:
            logger.warning("Google 翻译返回 400")
            return text

        resp.raise_for_status()
        match = re.findall(r'(?s)class="(?:t0|result-container)">(.*?)<', resp.text)
        if match:
            return html_mod.unescape(match[0])
        else:
            logger.warning("Google 翻译结果解析失败")
            return text

    @classmethod
    def is_available(cls) -> bool:
        return True
