"""
ClipLingo 统一错误码体系

所有业务错误通过 ErrorCode 枚举标识，ClipLingoError 异常携带错误码。
translate_error() 从任意异常提取错误码和中文提示。
"""

from enum import Enum


class ErrorCode(str, Enum):
    """错误码枚举"""
    API_KEY_INVALID = "API_KEY_INVALID"
    API_KEY_MISSING = "API_KEY_MISSING"
    API_QUOTA_EXCEEDED = "API_QUOTA_EXCEEDED"
    API_RATE_LIMITED = "API_RATE_LIMITED"
    API_TIMEOUT = "API_TIMEOUT"
    API_CONNECTION_FAILED = "API_CONNECTION_FAILED"
    API_MODEL_NOT_FOUND = "API_MODEL_NOT_FOUND"
    FFMPEG_NOT_FOUND = "FFMPEG_NOT_FOUND"
    FFMPEG_FAILED = "FFMPEG_FAILED"
    WHISPER_NOT_INSTALLED = "WHISPER_NOT_INSTALLED"
    WHISPER_MODEL_FAILED = "WHISPER_MODEL_FAILED"
    WHISPER_TRANSCRIBE_FAILED = "WHISPER_TRANSCRIBE_FAILED"
    WHISPER_TIMEOUT = "WHISPER_TIMEOUT"
    SUBTITLE_EMPTY = "SUBTITLE_EMPTY"
    SUBTITLE_PARSE_FAILED = "SUBTITLE_PARSE_FAILED"
    AI_PROCESS_FAILED = "AI_PROCESS_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.API_KEY_INVALID: "API Key 无效，请在设置中重新配置",
    ErrorCode.API_KEY_MISSING: "请先在设置中填写 API Key",
    ErrorCode.API_QUOTA_EXCEEDED: "API 余额不足，请充值后重试",
    ErrorCode.API_RATE_LIMITED: "请求太频繁，请稍后再试",
    ErrorCode.API_TIMEOUT: "API 请求超时，请检查网络连接",
    ErrorCode.API_CONNECTION_FAILED: "无法连接到 API 服务器，请检查 API 地址",
    ErrorCode.API_MODEL_NOT_FOUND: "所选模型不存在，请在设置中更换模型",
    ErrorCode.FFMPEG_NOT_FOUND: "未检测到 ffmpeg，请确保程序完整安装",
    ErrorCode.FFMPEG_FAILED: "媒体处理失败，视频文件可能已损坏",
    ErrorCode.WHISPER_NOT_INSTALLED: "Whisper 未安装，请在设置中安装语音识别组件",
    ErrorCode.WHISPER_MODEL_FAILED: "Whisper 模型下载失败，请检查网络或手动下载模型",
    ErrorCode.WHISPER_TRANSCRIBE_FAILED: "语音识别失败，请重试或手动导入字幕",
    ErrorCode.WHISPER_TIMEOUT: "语音识别超时，请尝试使用更小的模型",
    ErrorCode.SUBTITLE_EMPTY: "没有符合条件的字幕，请调整筛选条件",
    ErrorCode.SUBTITLE_PARSE_FAILED: "字幕文件格式错误，请检查文件编码",
    ErrorCode.AI_PROCESS_FAILED: "AI 处理失败，请检查 API 配置",
    ErrorCode.INTERNAL_ERROR: "程序内部错误，请重启程序后重试。如仍出现，请查看日志或提交 issue",
}


class ClipLingoError(Exception):
    """业务异常，携带错误码"""

    def __init__(self, code: ErrorCode, detail: str = ""):
        self.code = code
        self.detail = detail
        self.message = ERROR_MESSAGES.get(code, "未知错误")
        super().__init__(detail or self.message)


def get_message(code: ErrorCode, detail: str = "") -> str:
    """获取错误码对应的中文提示，detail 非空时附加在后面"""
    base = ERROR_MESSAGES.get(code, "未知错误")
    return f"{base}：{detail}" if detail else base


# 原始错误信息 -> 错误码的关键词映射
_KEYWORD_MAP: list[tuple[str, ErrorCode]] = [
    # API Key
    ("invalid api key", ErrorCode.API_KEY_INVALID),
    ("incorrect api key", ErrorCode.API_KEY_INVALID),
    ("authentication", ErrorCode.API_KEY_INVALID),
    ("unauthorized", ErrorCode.API_KEY_INVALID),
    ("401", ErrorCode.API_KEY_INVALID),
    # 余额
    ("insufficient", ErrorCode.API_QUOTA_EXCEEDED),
    ("quota", ErrorCode.API_QUOTA_EXCEEDED),
    ("billing", ErrorCode.API_QUOTA_EXCEEDED),
    # 限流
    ("rate limit", ErrorCode.API_RATE_LIMITED),
    ("429", ErrorCode.API_RATE_LIMITED),
    ("too many requests", ErrorCode.API_RATE_LIMITED),
    # 超时
    ("timeout", ErrorCode.API_TIMEOUT),
    ("timeouterror", ErrorCode.API_TIMEOUT),
    ("timed out", ErrorCode.API_TIMEOUT),
    # 连接
    ("connection", ErrorCode.API_CONNECTION_FAILED),
    ("unreachable", ErrorCode.API_CONNECTION_FAILED),
    ("refused", ErrorCode.API_CONNECTION_FAILED),
    ("reset by peer", ErrorCode.API_CONNECTION_FAILED),
    # 模型
    ("model does not exist", ErrorCode.API_MODEL_NOT_FOUND),
    ("model_not_found", ErrorCode.API_MODEL_NOT_FOUND),
    # ffmpeg
    ("ffmpeg", ErrorCode.FFMPEG_NOT_FOUND),
    ("ffprobe", ErrorCode.FFMPEG_NOT_FOUND),
    # Whisper（仅匹配明确的"未安装"提示，避免误判其他 whisper 相关错误）
    ("whisper 未安装", ErrorCode.WHISPER_NOT_INSTALLED),
    ("whisper not installed", ErrorCode.WHISPER_NOT_INSTALLED),
    # 字幕解析
    ("no subtitles", ErrorCode.SUBTITLE_EMPTY),
    ("没有符合条件的字幕", ErrorCode.SUBTITLE_EMPTY),
    ("字幕文件格式", ErrorCode.SUBTITLE_PARSE_FAILED),
    ("无法解析字幕", ErrorCode.SUBTITLE_PARSE_FAILED),
    ("could not parse subtitle", ErrorCode.SUBTITLE_PARSE_FAILED),
]


def translate_error(exc: Exception) -> tuple[ErrorCode, str]:
    """
    从任意异常提取错误码和中文提示。

    Returns:
        (ErrorCode, 中文提示)
    """
    # ClipLingoError 直接取 code
    if isinstance(exc, ClipLingoError):
        return exc.code, get_message(exc.code, exc.detail)

    msg = str(exc)
    lower = msg.lower()

    # 关键词匹配
    for keyword, code in _KEYWORD_MAP:
        if keyword in lower:
            return code, get_message(code, msg)

    # 未匹配到，返回内部错误
    return ErrorCode.INTERNAL_ERROR, get_message(ErrorCode.INTERNAL_ERROR, msg[:200])


# 瞬态错误关键词（用于重试判断）
_TRANSIENT_KEYWORDS = (
    "connection", "timeout", "timeouterror", "rate limit", "server error",
    "503", "502", "500", "429", "unreachable", "refused",
    "reset by peer", "too many requests",
)


def is_transient(exc: Exception) -> bool:
    """判断是否为瞬态错误（可重试）"""
    if isinstance(exc, ClipLingoError):
        return exc.code in (
            ErrorCode.API_TIMEOUT,
            ErrorCode.API_CONNECTION_FAILED,
            ErrorCode.API_RATE_LIMITED,
        )
    lower = str(exc).lower()
    return any(kw in lower for kw in _TRANSIENT_KEYWORDS)
