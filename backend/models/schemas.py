"""
Pydantic 模型定义
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class SubtitleItem(BaseModel):
    """字幕条目"""
    index: int
    start_sec: float
    end_sec: float
    text: str
    duration: float = Field(default=0, description="字幕时长（秒）")

    @classmethod
    def from_subtitle(cls, sub) -> "SubtitleItem":
        """从核心模块的 Subtitle dataclass 转换"""
        return cls(
            index=sub.index,
            start_sec=round(sub.start_sec, 3),
            end_sec=round(sub.end_sec, 3),
            text=sub.text,
            duration=round(sub.end_sec - sub.start_sec, 3)
        )

    class Config:
        json_schema_extra = {
            "example": {
                "index": 1,
                "start_sec": 83.456,
                "end_sec": 85.789,
                "text": "Hello, how are you?",
                "duration": 2.333
            }
        }


class SubtitleListResponse(BaseModel):
    """字幕列表响应"""
    subtitles: List[SubtitleItem]
    total: int
    filtered: int


class EmbeddedSubtitleStream(BaseModel):
    """视频内嵌字幕流信息"""
    index: int
    codec: str
    language: str = ""
    title: str = ""
    text_based: bool = True


class ExtractEmbeddedResponse(BaseModel):
    """提取内嵌字幕响应"""
    found: bool
    streams: list = []
    extracted: Optional[dict] = None
    message: str = ""


class ProcessRequest(BaseModel):
    """处理请求"""
    video_path: str
    subtitle_path: str
    min_duration: float = 1.0
    output_dir: str = "./output"
    api_key: Optional[str] = None


class ProcessProgress(BaseModel):
    """处理进度"""
    step: str
    message: str
    progress: float = 0.0
    total_steps: int = 5
    current_step: int = 0


class ProcessedCard(BaseModel):
    """处理后的卡片"""
    sentence: str
    translation: str
    notes: str
    word: Optional[str] = None
    definition: Optional[str] = None
    start_sec: float
    end_sec: float
    audio_path: Optional[str] = None
    screenshot_path: Optional[str] = None


class ProcessResult(BaseModel):
    """处理结果"""
    success: bool
    message: str
    cards_count: int
    apkg_path: Optional[str] = None
    cards: List[ProcessedCard] = []


class ApiKeyConfig(BaseModel):
    """API Key 配置"""
    api_key: str


class AIRecommendRequest(BaseModel):
    """AI 推荐请求"""
    subtitles: List[SubtitleItem]
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None
    batch_size: int = 30
    ai_concurrency: int = Field(default=3, ge=1, le=20, description="并发请求数")
    source_language: str = Field(default="en", description="源语言代码，如 en、ja、ko")
    target_language: str = Field(default="zh", description="目标语言代码，如 zh、en、ja")
    correct_text: bool = Field(default=False, description="是否允许 AI 修正字幕原文")


class AIRecommendItem(BaseModel):
    """单条推荐结果"""
    index: int
    include: bool
    reason: str
    translation: Optional[str] = None
    notes: Optional[str] = None
    word: Optional[str] = None
    definition: Optional[str] = None
    corrected_text: Optional[str] = None


class AIRecommendResponse(BaseModel):
    """AI 推荐响应"""
    recommendations: List[AIRecommendItem]


class AIAnnotateRequest(BaseModel):
    """AI 注释请求（第二阶段：根据用途生成翻译和注释）"""
    subtitles: List[SubtitleItem]
    purpose: str = Field(default="grammar", description="用途：'grammar'（语法句型）或 'vocab'（背单词）")
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model_name: Optional[str] = None
    custom_prompt: Optional[str] = None
    batch_size: int = 30
    ai_concurrency: int = Field(default=3, ge=1, le=20, description="并发请求数")
    source_language: str = Field(default="en", description="源语言代码")
    target_language: str = Field(default="zh", description="目标语言代码")
    task_id: Optional[str] = Field(default=None, description="任务ID，用于查询预热缓存")


class CardPreviewRequest(BaseModel):
    """卡片预览请求"""
    cards: List[ProcessedCard]


class TranslateBatchRequest(BaseModel):
    """批量翻译请求"""
    texts: List[str] = Field(default=[], description="待翻译的文本列表")
    service: str = Field(default="bing", description="翻译服务 ID：bing / google")
    source_lang: str = Field(default="auto", description="源语言代码")
    target_lang: str = Field(default="zh", description="目标语言代码")


class TranslateBatchResponse(BaseModel):
    """批量翻译响应"""
    translations: List[str] = Field(default=[], description="翻译结果列表")


class ASREngineInfo(BaseModel):
    """ASR 引擎信息"""
    id: str
    name: str
    available: bool


class TranslateServiceInfo(BaseModel):
    """翻译服务信息"""
    id: str
    name: str
    available: bool
