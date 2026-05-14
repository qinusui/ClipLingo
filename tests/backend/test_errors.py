"""测试 translate_error 错误归类，确保不会误判"""
import pytest
from errors import translate_error, ErrorCode, ClipLingoError


class TestTranslateError:
    """验证 translate_error 对不同异常的分类是否正确"""

    def test_whisper_not_installed_explicit(self):
        """明确提示 Whisper 未安装，应归类为 WHISPER_NOT_INSTALLED"""
        code, _ = translate_error(RuntimeError("Whisper 未安装，请先安装 Whisper"))
        assert code == ErrorCode.WHISPER_NOT_INSTALLED

    def test_whisper_process_crash_not_misclassified(self):
        """子进程崩溃的笼统错误，不应归类为 WHISPER_NOT_INSTALLED"""
        code, _ = translate_error(RuntimeError("Whisper 进程异常退出 (code=1)"))
        assert code != ErrorCode.WHISPER_NOT_INSTALLED

    def test_transcribe_subprocess_crash_not_misclassified(self):
        """新错误消息不含 whisper 未安装，不应归类为 WHISPER_NOT_INSTALLED"""
        code, _ = translate_error(RuntimeError("转录子进程异常退出 (code=1)"))
        assert code != ErrorCode.WHISPER_NOT_INSTALLED

    def test_model_download_failure_not_misclassified(self):
        """模型下载失败的错误，不应归类为 WHISPER_NOT_INSTALLED"""
        code, _ = translate_error(RuntimeError("model download failed: SSL certificate verify failed"))
        assert code != ErrorCode.WHISPER_NOT_INSTALLED

    def test_cliplingo_error_preserves_code(self):
        """ClipLingoError 精确携带错误码"""
        code, _ = translate_error(ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED, "model crash"))
        assert code == ErrorCode.WHISPER_MODEL_FAILED

    def test_whisper_english_not_installed(self):
        """英文提示 Whisper not installed 也应匹配"""
        code, _ = translate_error(RuntimeError("Whisper not installed, please install first"))
        assert code == ErrorCode.WHISPER_NOT_INSTALLED

    def test_unknown_error_defaults_to_internal(self):
        """无法识别的错误默认为 INTERNAL_ERROR"""
        code, _ = translate_error(RuntimeError("something completely unexpected"))
        assert code == ErrorCode.INTERNAL_ERROR

    def test_ai_empty_result_not_subtitle_parse_error(self):
        """AI 筛选后无保留字幕不应归类为 SUBTITLE_PARSE_FAILED"""
        code, _ = translate_error(RuntimeError("AI 处理后没有保留的字幕"))
        assert code != ErrorCode.SUBTITLE_PARSE_FAILED

    def test_subtitle_parse_keyword_still_matches_real_errors(self):
        """真实字幕解析错误仍能正确归类"""
        code, _ = translate_error(RuntimeError("字幕文件格式错误: illegal srt syntax"))
        assert code == ErrorCode.SUBTITLE_PARSE_FAILED
        code2, _ = translate_error(RuntimeError("无法解析字幕，请检查编码"))
        assert code2 == ErrorCode.SUBTITLE_PARSE_FAILED
