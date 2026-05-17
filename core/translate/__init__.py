"""
翻译服务注册表 + 工厂函数
"""
import logging
import re
from typing import Optional

from .base import BaseTranslator

logger = logging.getLogger(__name__)

# 翻译器注册表：SERVICE_ID → 翻译器类
TRANSLATOR_REGISTRY: dict[str, type[BaseTranslator]] = {}


def register_translator(cls: type[BaseTranslator]) -> type[BaseTranslator]:
    """装饰器：注册翻译服务"""
    TRANSLATOR_REGISTRY[cls.SERVICE_ID] = cls
    logger.info(f"注册翻译服务: {cls.SERVICE_ID} ({cls.SERVICE_NAME})")
    return cls


def get_available_translators() -> list[dict]:
    """获取所有可用翻译服务的列表（供前端展示）"""
    services = []
    for service_id, service_cls in TRANSLATOR_REGISTRY.items():
        services.append({
            "id": service_id,
            "name": service_cls.SERVICE_NAME,
            "available": service_cls.is_available(),
        })
    return services


def create_translator(service_id: str, **kwargs) -> BaseTranslator:
    """根据服务 ID 创建翻译器实例"""
    if service_id not in TRANSLATOR_REGISTRY:
        raise ValueError(f"未知的翻译服务: {service_id}，可用服务: {list(TRANSLATOR_REGISTRY.keys())}")
    return TRANSLATOR_REGISTRY[service_id](**kwargs)


def translate_batch(
    texts: list[str],
    service_id: str = "bing",
    source_lang: str = "auto",
    target_lang: str = "zh",
) -> list[str]:
    """批量翻译文本的便捷函数

    Args:
        texts: 待翻译的文本列表
        service_id: 翻译服务 ID
        source_lang: 源语言代码
        target_lang: 目标语言代码

    Returns:
        翻译结果列表
    """
    translator = create_translator(service_id)
    return translator.translate(texts, source_lang, target_lang)


# 导入翻译器实现，触发 @register_translator 装饰器填充注册表
import core.translate.bing    # noqa: E402, F401
import core.translate.google  # noqa: E402, F401
