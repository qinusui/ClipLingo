"""
ASR 引擎注册表 + 工厂函数
"""
import logging
from typing import Optional

from .base import BaseASREngine

logger = logging.getLogger(__name__)

# 引擎注册表：ENGINE_ID → 引擎类
ASR_ENGINE_REGISTRY: dict[str, type[BaseASREngine]] = {}


def register_engine(cls: type[BaseASREngine]) -> type[BaseASREngine]:
    """装饰器：注册 ASR 引擎"""
    ASR_ENGINE_REGISTRY[cls.ENGINE_ID] = cls
    logger.info(f"注册 ASR 引擎: {cls.ENGINE_ID} ({cls.ENGINE_NAME})")
    return cls


def get_available_engines() -> list[dict]:
    """获取所有可用引擎的列表（供前端展示）"""
    engines = []
    for engine_id, engine_cls in ASR_ENGINE_REGISTRY.items():
        engines.append({
            "id": engine_id,
            "name": engine_cls.ENGINE_NAME,
            "available": engine_cls.is_available(),
        })
    return engines


def create_engine(engine_id: str, **kwargs) -> BaseASREngine:
    """根据引擎 ID 创建引擎实例"""
    if engine_id not in ASR_ENGINE_REGISTRY:
        raise ValueError(f"未知的 ASR 引擎: {engine_id}，可用引擎: {list(ASR_ENGINE_REGISTRY.keys())}")
    return ASR_ENGINE_REGISTRY[engine_id](**kwargs)


# 导入引擎实现，触发 @register_engine 装饰器填充注册表
import core.asr.whisper_engine  # noqa: E402, F401
import core.asr.bcut_engine     # noqa: E402, F401
