"""
翻译服务抽象基类
"""
from abc import ABC, abstractmethod


class BaseTranslator(ABC):
    """翻译服务抽象基类 — 所有翻译服务的统一接口"""

    SERVICE_ID: str = ""       # 唯一标识，如 "bing"、"google"
    SERVICE_NAME: str = ""     # 显示名称，如 "微软翻译（Bing）"

    @abstractmethod
    def translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh",
    ) -> list[str]:
        """翻译文本列表

        Args:
            texts: 待翻译的文本列表
            source_lang: 源语言代码
            target_lang: 目标语言代码

        Returns:
            翻译结果列表，与输入等长
        """
        ...

    @classmethod
    def is_available(cls) -> bool:
        """检查翻译服务在当前环境是否可用"""
        return True
