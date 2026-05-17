"""
翻译相关 API
"""
from fastapi import APIRouter, HTTPException
from models.schemas import TranslateBatchRequest, TranslateBatchResponse, TranslateServiceInfo

import logging
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.append(str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/services")
async def get_translate_services():
    """获取可用的翻译服务列表"""
    import core.translate.bing    # noqa: F401
    import core.translate.google  # noqa: F401
    from core.translate import get_available_translators
    services = get_available_translators()
    return {"services": [TranslateServiceInfo(**s).model_dump() for s in services]}


@router.post("/batch", response_model=TranslateBatchResponse)
async def translate_batch(request: TranslateBatchRequest):
    """批量翻译文本"""
    if not request.texts:
        return TranslateBatchResponse(translations=[])

    if request.service not in ("bing", "google"):
        raise HTTPException(status_code=400, detail=f"未知的翻译服务: {request.service}")

    import core.translate.bing    # noqa: F401
    import core.translate.google  # noqa: F401
    from core.translate import create_translator

    try:
        translator = create_translator(request.service)
        translations = translator.translate(
            request.texts,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
        return TranslateBatchResponse(translations=translations)
    except Exception as e:
        logger.error(f"翻译失败: {e}")
        raise HTTPException(status_code=500, detail=f"翻译失败: {str(e)}")
