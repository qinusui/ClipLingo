"""语言代码到显示名称的映射 — 唯一的 source of truth"""

LANGUAGE_NAMES: dict[str, str] = {
    "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "it": "意大利语",
    "pt": "葡萄牙语", "ru": "俄语", "ar": "阿拉伯语", "th": "泰语",
    "vi": "越南语", "nl": "荷兰语", "sv": "瑞典语", "pl": "波兰语",
    "tr": "土耳其语", "hi": "印地语", "id": "印尼语", "uk": "乌克兰语",
}


def get_name(code: str) -> str:
    """根据语言代码获取显示名称，未知代码直接返回原代码"""
    return LANGUAGE_NAMES.get(code, code)
