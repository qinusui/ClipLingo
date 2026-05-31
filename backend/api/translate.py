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
    import core.translate.bing              # noqa: F401
    import core.translate.google            # noqa: F401
    import core.translate.deepl             # noqa: F401
    import core.translate.openai_translate  # noqa: F401
    from core.translate import get_available_translators
    services = get_available_translators()
    return {"services": [TranslateServiceInfo(**s).model_dump() for s in services]}


@router.post("/batch", response_model=TranslateBatchResponse)
async def translate_batch(request: TranslateBatchRequest):
    """批量翻译文本"""
    if not request.texts:
        return TranslateBatchResponse(translations=[])

    import core.translate.bing              # noqa: F401
    import core.translate.google            # noqa: F401
    import core.translate.deepl             # noqa: F401
    import core.translate.openai_translate  # noqa: F401
    from core.translate import create_translator, TRANSLATOR_REGISTRY

    if request.service not in TRANSLATOR_REGISTRY:
        raise HTTPException(status_code=400, detail=f"未知的翻译服务: {request.service}")

    try:
        # 构建翻译器参数（DeepL / OpenAI 需要 API Key）
        kwargs: dict = {}
        if request.service == "deepl":
            if not request.api_key:
                raise HTTPException(status_code=400, detail="DeepL 翻译需要 API Key")
            kwargs["api_key"] = request.api_key
        elif request.service == "openai":
            if not request.api_key:
                raise HTTPException(status_code=400, detail="AI 翻译需要 API Key")
            kwargs["api_key"] = request.api_key
            if request.api_base:
                kwargs["api_base"] = request.api_base
            if request.model_name:
                kwargs["model_name"] = request.model_name

        translator = create_translator(request.service, **kwargs)
        translations = translator.translate(
            request.texts,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
        )
        return TranslateBatchResponse(translations=translations)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"翻译失败: {e}")
        raise HTTPException(status_code=500, detail=f"翻译失败: {str(e)}")
