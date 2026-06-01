"""
whisper_transcribe 模块测试
覆盖：segments_to_srt_format、save_as_srt、transcribe_video（mock）
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from core.whisper_transcribe import segments_to_srt_format, save_as_srt, transcribe_video


# ── 辅助 ────────────────────────────────────────────────

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world"},
    {"start": 3.0, "end": 5.123, "text": "Test subtitle"},
    {"start": 10.0, "end": 15.5, "text": "Final line"},
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  segments_to_srt_format
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSegmentsToSRTFormat:
    """段落转 SRT 格式"""

    def test_basic_conversion(self):
        """基本转换"""
        result = segments_to_srt_format(SAMPLE_SEGMENTS)

        lines = result.strip().split("\n")
        # 每条字幕 4 行：序号、时间、文本、空行
        assert lines[0] == "1"
        assert lines[1] == "00:00:00,000 --> 00:00:02,500"
        assert lines[2] == "Hello world"
        assert lines[3] == ""

    def test_index_numbering(self):
        """序号应从 1 开始连续"""
        result = segments_to_srt_format(SAMPLE_SEGMENTS)
        lines = result.strip().split("\n")

        assert lines[0] == "1"
        assert lines[4] == "2"
        assert lines[8] == "3"

    def test_time_format_precision(self):
        """时间格式精度到毫秒"""
        result = segments_to_srt_format(SAMPLE_SEGMENTS)

        assert "00:00:03,000 --> 00:00:05,123" in result

    def test_hours_formatting(self):
        """超过 1 小时的时间格式"""
        segments = [{"start": 3661.5, "end": 3665.0, "text": "Long video"}]
        result = segments_to_srt_format(segments)

        assert "01:01:01,500 --> 01:01:05,000" in result

    def test_empty_segments(self):
        """空段落列表应返回空字符串"""
        result = segments_to_srt_format([])
        assert result == ""

    def test_single_segment(self):
        """单个段落"""
        segments = [{"start": 0.0, "end": 1.0, "text": "Only one"}]
        result = segments_to_srt_format(segments)

        lines = result.strip().split("\n")
        assert len(lines) == 3  # 序号、时间、文本（无尾部空行）
        assert lines[0] == "1"
        assert lines[2] == "Only one"

    def test_zero_duration_segment(self):
        """零时长段落"""
        segments = [{"start": 5.0, "end": 5.0, "text": "Instant"}]
        result = segments_to_srt_format(segments)
        assert "00:00:05,000 --> 00:00:05,000" in result

    def test_milliseconds_rounding(self):
        """毫秒应截断而非四舍五入"""
        segments = [{"start": 0.9999, "end": 1.0001, "text": "Precision"}]
        result = segments_to_srt_format(segments)
        # 0.9999 → 999ms, 1.0001 → 0ms (int truncation)
        assert "00:00:00,999 --> 00:00:01,000" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  save_as_srt
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSaveAsSRT:
    """保存为 SRT 文件"""

    def test_save_creates_file(self, tmp_path):
        """应创建 SRT 文件"""
        output_path = tmp_path / "output.srt"
        save_as_srt(SAMPLE_SEGMENTS, str(output_path))

        assert output_path.exists()

    def test_save_content_correct(self, tmp_path):
        """文件内容应正确"""
        output_path = tmp_path / "output.srt"
        save_as_srt(SAMPLE_SEGMENTS, str(output_path))

        content = output_path.read_text(encoding="utf-8")
        assert "Hello world" in content
        assert "Test subtitle" in content
        assert "Final line" in content

    def test_save_utf8_encoding(self, tmp_path):
        """应使用 UTF-8 编码"""
        segments = [{"start": 0.0, "end": 1.0, "text": "中文测试"}]
        output_path = tmp_path / "chinese.srt"
        save_as_srt(segments, str(output_path))

        content = output_path.read_text(encoding="utf-8")
        assert "中文测试" in content

    def test_save_empty_segments(self, tmp_path):
        """空段落应创建空文件"""
        output_path = tmp_path / "empty.srt"
        save_as_srt([], str(output_path))

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert content == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  transcribe_video (mocked)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTranscribeVideo:
    """转录视频（mock faster-whisper）"""

    @patch("faster_whisper.WhisperModel")
    def test_normal_transcription(self, mock_model_cls):
        """正常转录流程"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model

        # 模拟转录结果
        mock_segment1 = Mock()
        mock_segment1.start = 0.0
        mock_segment1.end = 2.0
        mock_segment1.text = "Hello"

        mock_segment2 = Mock()
        mock_segment2.start = 3.0
        mock_segment2.end = 5.0
        mock_segment2.text = "World"

        mock_info = Mock()
        mock_info.language = "en"

        mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], mock_info)

        result = transcribe_video("fake_video.mp4", model_name="base", language="en")

        assert len(result) == 2
        assert result[0]["start"] == 0.0
        assert result[0]["text"] == "Hello"

    @patch("faster_whisper.WhisperModel")
    def test_empty_transcription(self, mock_model_cls):
        """空转录结果"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model
        mock_model.transcribe.return_value = ([], Mock())

        result = transcribe_video("fake_video.mp4")
        assert result == []

    @patch("faster_whisper.WhisperModel")
    def test_whitespace_only_segments_skipped(self, mock_model_cls):
        """空白文本段落应被跳过"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model

        mock_seg1 = Mock()
        mock_seg1.start = 0.0
        mock_seg1.end = 1.0
        mock_seg1.text = "   "  # 空白

        mock_seg2 = Mock()
        mock_seg2.start = 2.0
        mock_seg2.end = 3.0
        mock_seg2.text = "Valid"

        mock_model.transcribe.return_value = ([mock_seg1, mock_seg2], Mock())

        result = transcribe_video("fake_video.mp4")
        assert len(result) == 1
        assert result[0]["text"] == "Valid"

    @patch("faster_whisper.WhisperModel")
    def test_model_name_passed(self, mock_model_cls):
        """模型名称应正确传递"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model
        mock_model.transcribe.return_value = ([], Mock())

        transcribe_video("video.mp4", model_name="large-v2")

        mock_model_cls.assert_called_once_with("large-v2")

    @patch("faster_whisper.WhisperModel")
    def test_language_auto_detect(self, mock_model_cls):
        """language=None 应启用自动检测"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model
        mock_model.transcribe.return_value = ([], Mock())

        transcribe_video("video.mp4", language=None)

        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["language"] is None

    @patch("faster_whisper.WhisperModel")
    def test_vad_filter_enabled(self, mock_model_cls):
        """应启用 VAD 过滤"""
        mock_model = Mock()
        mock_model_cls.return_value = mock_model
        mock_model.transcribe.return_value = ([], Mock())

        transcribe_video("video.mp4")

        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs["vad_filter"] is True
