"""
ChunkedASR 分片转录测试
覆盖：短音频直接转录、长音频分片、分片规划、结果合并、异常处理
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from core.asr.chunked_asr import (
    ChunkedASR, _get_audio_duration_sec,
    DEFAULT_CHUNK_LENGTH_SEC, DEFAULT_CHUNK_OVERLAP_SEC, DEFAULT_CHUNK_CONCURRENCY,
)
from core.asr.base import BaseASREngine


# ── 辅助 ────────────────────────────────────────────────

class MockASREngine(BaseASREngine):
    """模拟 ASR 引擎"""

    def __init__(self, segments=None):
        self._segments = segments or []
        self.call_count = 0

    def transcribe(self, audio_path: str, language=None, progress_callback=None) -> list[dict]:
        self.call_count += 1
        return self._segments

    @property
    def name(self) -> str:
        return "mock"

    @classmethod
    def is_available(cls) -> bool:
        return True


def _make_segments(n: int = 2, start_offset: float = 0.0) -> list[dict]:
    """生成模拟转录段落"""
    return [
        {"start": start_offset + i * 2.0, "end": start_offset + i * 2.0 + 1.5, "text": f"Segment {i}"}
        for i in range(n)
    ]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  _get_audio_duration_sec
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetAudioDuration:
    """获取音频时长"""

    @patch("core.asr.chunked_asr.subprocess.run")
    def test_normal_duration(self, mock_run):
        """正常获取时长"""
        mock_run.return_value = Mock(stdout="120.5\n", returncode=0)
        result = _get_audio_duration_sec("fake.mp3")
        assert result == pytest.approx(120.5)

    @patch("core.asr.chunked_asr.subprocess.run")
    def test_ffprobe_not_found(self, mock_run):
        """ffprobe 不存在"""
        mock_run.side_effect = FileNotFoundError()
        result = _get_audio_duration_sec("fake.mp3")
        assert result == 0.0

    @patch("core.asr.chunked_asr.subprocess.run")
    def test_ffprobe_error(self, mock_run):
        """ffprobe 执行错误"""
        mock_run.side_effect = Exception("Command failed")
        result = _get_audio_duration_sec("fake.mp3")
        assert result == 0.0

    @patch("core.asr.chunked_asr.subprocess.run")
    def test_empty_output(self, mock_run):
        """ffprobe 输出为空"""
        mock_run.return_value = Mock(stdout="", returncode=0)
        result = _get_audio_duration_sec("fake.mp3")
        assert result == 0.0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ChunkedASR 初始化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestChunkedASRInit:
    """ChunkedASR 初始化"""

    def test_default_params(self):
        """默认参数"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine)

        assert chunked.chunk_length_sec == DEFAULT_CHUNK_LENGTH_SEC
        assert chunked.chunk_overlap_sec == DEFAULT_CHUNK_OVERLAP_SEC
        assert chunked.chunk_concurrency == DEFAULT_CHUNK_CONCURRENCY

    def test_custom_params(self):
        """自定义参数"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=300, chunk_overlap=20, chunk_concurrency=5)

        assert chunked.chunk_length_sec == 300
        assert chunked.chunk_overlap_sec == 20
        assert chunked.chunk_concurrency == 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  _plan_chunks
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestPlanChunks:
    """分片规划"""

    def test_short_audio_single_chunk(self):
        """短音频只有一块"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=600)

        chunks = chunked._plan_chunks(300.0)  # 5 分钟 < 10 分钟
        assert len(chunks) == 1
        assert chunks[0][0] == 0.0  # start
        assert chunks[0][1] == 300.0  # end

    def test_long_audio_multiple_chunks(self):
        """长音频多块"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = chunked._plan_chunks(150.0)  # 2.5 分钟
        # 第1块: 0-60s, 第2块: 50-110s, 第3块: 100-150s
        assert len(chunks) >= 2

    def test_exact_length(self):
        """音频长度恰好等于 chunk_length"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = chunked._plan_chunks(60.0)
        assert len(chunks) == 1

    def test_offset_calculation(self):
        """偏移量计算"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = chunked._plan_chunks(120.0)
        # 第1块: (0, 60, 0)
        assert chunks[0] == (0.0, 60.0, 0)
        # 第2块: (50, 110, 50000)
        assert chunks[1][0] == 50.0
        assert chunks[1][2] == 50000


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  transcribe — 短音频
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTranscribeShortAudio:
    """短音频直接转录"""

    @patch("core.asr.chunked_asr._get_audio_duration_sec")
    def test_short_audio_direct(self, mock_duration):
        """短音频直接调用引擎"""
        mock_duration.return_value = 30.0  # 30 秒 < 默认 10 分钟

        segments = _make_segments(3)
        engine = MockASREngine(segments)
        chunked = ChunkedASR(engine)

        result = chunked.transcribe("fake.mp3")

        assert result == segments
        assert engine.call_count == 1

    @patch("core.asr.chunked_asr._get_audio_duration_sec")
    def test_zero_duration_direct(self, mock_duration):
        """无法获取时长时直接转录"""
        mock_duration.return_value = 0.0

        segments = _make_segments(1)
        engine = MockASREngine(segments)
        chunked = ChunkedASR(engine)

        result = chunked.transcribe("fake.mp3")
        assert result == segments


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  transcribe — 长音频（mock ffmpeg）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestTranscribeLongAudio:
    """长音频分片转录"""

    @patch("core.asr.chunked_asr.subprocess.run")
    @patch("core.asr.chunked_asr._get_audio_duration_sec")
    def test_long_audio_chunked(self, mock_duration, mock_ffmpeg):
        """长音频应被分片转录"""
        mock_duration.return_value = 150.0  # 2.5 分钟
        mock_ffmpeg.return_value = Mock(returncode=0)

        segments = _make_segments(2)
        engine = MockASREngine(segments)
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10, chunk_concurrency=1)

        result = chunked.transcribe("fake.mp3")

        # 应调用多次（至少 2 块）
        assert engine.call_count >= 2
        assert len(result) > 0

    @patch("core.asr.chunked_asr.subprocess.run")
    @patch("core.asr.chunked_asr._get_audio_duration_sec")
    def test_progress_callback_called(self, mock_duration, mock_ffmpeg):
        """进度回调应被调用"""
        mock_duration.return_value = 150.0
        mock_ffmpeg.return_value = Mock(returncode=0)

        engine = MockASREngine(_make_segments(1))
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        progress_calls = []

        def callback(progress, message):
            progress_calls.append((progress, message))

        chunked.transcribe("fake.mp3", progress_callback=callback)

        assert len(progress_calls) > 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  _merge_results
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestMergeResults:
    """合并分片结果"""

    def test_merge_single_chunk(self):
        """单块合并"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(0.0, 60.0, 0)]
        results = [[{"start": 1.0, "end": 2.0, "text": "Hello"}]]

        merged = chunked._merge_results(results, chunks)

        assert len(merged) == 1
        assert merged[0]["text"] == "Hello"

    def test_merge_multiple_chunks(self):
        """多块合并"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(0.0, 60.0, 0), (50.0, 110.0, 50000)]
        results = [
            [{"start": 5.0, "end": 6.0, "text": "First"}],
            [{"start": 5.0, "end": 6.0, "text": "Second"}],
        ]

        merged = chunked._merge_results(results, chunks)

        assert len(merged) >= 2
        # 应按 start 排序
        assert merged[0]["start"] <= merged[1]["start"]

    def test_merge_with_none_results(self):
        """部分分片失败"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(0.0, 60.0, 0), (50.0, 110.0, 50000)]
        results = [
            [{"start": 1.0, "end": 2.0, "text": "OK"}],
            None,  # 第二块失败
        ]

        merged = chunked._merge_results(results, chunks)

        assert len(merged) == 1
        assert merged[0]["text"] == "OK"

    def test_merge_deduplication(self):
        """去重：相同文本应合并"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(0.0, 60.0, 0), (50.0, 110.0, 50000)]
        results = [
            [{"start": 55.0, "end": 56.0, "text": "Duplicate"}],
            [{"start": 5.0, "end": 6.0, "text": "Duplicate"}],  # 相同文本
        ]

        merged = chunked._merge_results(results, chunks)

        # 去重后应只有一条
        texts = [s["text"] for s in merged]
        assert texts.count("Duplicate") == 1

    def test_merge_empty_results(self):
        """空结果合并"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(0.0, 60.0, 0)]
        results = [[]]

        merged = chunked._merge_results(results, chunks)
        assert merged == []

    def test_merge_time_offset_applied(self):
        """时间偏移应正确应用"""
        engine = MockASREngine()
        chunked = ChunkedASR(engine, chunk_length=60, chunk_overlap=10)

        chunks = [(50.0, 110.0, 50000)]
        results = [[{"start": 5.0, "end": 6.0, "text": "Offset"}]]

        merged = chunked._merge_results(results, chunks)

        # 原始 start=5.0 + offset=50.0 = 55.0
        assert merged[0]["start"] == pytest.approx(55.0)
        assert merged[0]["end"] == pytest.approx(56.0)
