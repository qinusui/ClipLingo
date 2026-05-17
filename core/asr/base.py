"""
ASR 引擎抽象基类
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional


class BaseASREngine(ABC):
    """ASR 引擎抽象基类 — 所有语音识别引擎的统一接口"""

    ENGINE_ID: str = ""       # 唯一标识，如 "faster_whisper"、"bcut"
    ENGINE_NAME: str = ""     # 显示名称，如 "Faster Whisper（本地）"

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[dict]:
        """转录音频为字幕片段

        Args:
            audio_path: 音频文件路径
            language: 语言代码（None 表示自动检测）
            progress_callback: 进度回调 callback(progress: float, message: str)
                               progress 范围 0.0 ~ 1.0

        Returns:
            [{"start": float, "end": float, "text": str}, ...]
        """
        ...

    @classmethod
    def is_available(cls) -> bool:
        """检查引擎在当前环境是否可用"""
        return True
