"""
FasterWhisperEngine — 封装现有的 faster-whisper 本地引擎
"""
import logging
import sys
from pathlib import Path
from typing import Callable, Optional

from .base import BaseASREngine
from . import register_engine

_root = str(Path(__file__).parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
from errors import ClipLingoError, ErrorCode

logger = logging.getLogger(__name__)


@register_engine
class FasterWhisperEngine(BaseASREngine):
    """Faster Whisper 本地引擎 — 封装现有 whisper_manager + whisper_transcribe"""

    ENGINE_ID = "faster_whisper"
    ENGINE_NAME = "Faster Whisper（本地）"

    def __init__(self, model_name: str = "base"):
        self.model_name = model_name

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[dict]:
        from core.whisper_manager import load_model

        model = load_model(self.model_name)
        if model is None:
            raise ClipLingoError(
                ErrorCode.WHISPER_NOT_INSTALLED,
                f"Whisper 未安装或不可用，无法加载模型 {self.model_name}"
            )

        try:
            segments_iter, info = model.transcribe(
                audio_path,
                language=language,
                word_timestamps=True,
                vad_filter=True,
            )

            segments = []
            total_duration = info.duration if hasattr(info, "duration") else 0
            for seg in segments_iter:
                text = seg.text.strip()
                if text:
                    segments.append({
                        "start": seg.start,
                        "end": seg.end,
                        "text": text,
                    })
                    if progress_callback and total_duration > 0:
                        progress_callback(
                            min(seg.end / total_duration, 1.0),
                            f"转录中... {len(segments)} 段",
                        )

            if progress_callback:
                progress_callback(1.0, f"转录完成，共 {len(segments)} 段")
        except ClipLingoError:
            raise
        except Exception as e:
            raise ClipLingoError(
                ErrorCode.WHISPER_TRANSCRIBE_FAILED,
                f"语音识别失败: {e}"
            ) from e

        return segments

    @classmethod
    def is_available(cls) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False
