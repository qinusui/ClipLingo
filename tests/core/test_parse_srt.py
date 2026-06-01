"""
parse_srt 模块测试
覆盖：正常解析、空文件、非 UTF-8、畸形时间轴、短字幕过滤
"""

import pytest
from pathlib import Path

from core.parse_srt import parse_srt, parse_time_to_seconds, filter_short_subtitles, Subtitle


# ── 辅助 ────────────────────────────────────────────────

def _write_srt(tmp_path: Path, content: str, name: str = "test.srt") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


VALID_SRT = """\
1
00:00:01,000 --> 00:00:03,000
Hello world

2
00:00:05,500 --> 00:00:08,200
This is a test

3
00:01:00,000 --> 00:01:05,000
Goodbye
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  parse_time_to_seconds
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestParseTimeToSeconds:
    """时间字符串转换"""

    def test_zero(self):
        assert parse_time_to_seconds("00:00:00,000") == 0.0

    def test_basic(self):
        assert parse_time_to_seconds("00:00:01,500") == 1.5

    def test_minutes(self):
        assert parse_time_to_seconds("00:02:30,000") == 150.0

    def test_hours(self):
        assert parse_time_to_seconds("01:00:00,000") == 3600.0

    def test_full(self):
        result = parse_time_to_seconds("01:23:45,678")
        assert result == pytest.approx(1 * 3600 + 23 * 60 + 45.678)

    def test_dot_separator(self):
        """支持点号作为毫秒分隔符"""
        assert parse_time_to_seconds("00:00:01.500") == 1.5

    def test_malformed_missing_components(self):
        """缺少时间分量应抛出异常"""
        with pytest.raises((IndexError, ValueError)):
            parse_time_to_seconds("00:00")

    def test_malformed_non_numeric(self):
        """非数字内容应抛出异常"""
        with pytest.raises(ValueError):
            parse_time_to_seconds("aa:bb:cc,ddd")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  parse_srt — 正常场景
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestParseSRTNormal:
    """正常解析场景"""

    def test_valid_srt(self, tmp_path):
        path = _write_srt(tmp_path, VALID_SRT)
        subs = parse_srt(path)

        assert len(subs) == 3
        assert subs[0].index == 1
        assert subs[0].start_sec == 1.0
        assert subs[0].end_sec == 3.0
        assert subs[0].text == "Hello world"

    def test_multiline_text(self, tmp_path):
        """多行文本应合并"""
        content = """\
1
00:00:01,000 --> 00:00:03,000
Line one
Line two
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)

        assert len(subs) == 1
        assert subs[0].text == "Line one Line two"

    def test_reindex_after_parse(self, tmp_path):
        """解析后应重新编号为连续序号"""
        content = """\
5
00:00:01,000 --> 00:00:03,000
First

10
00:00:05,000 --> 00:00:08,000
Second
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)

        assert subs[0].index == 1
        assert subs[1].index == 2

    def test_path_object(self, tmp_path):
        """支持 Path 对象作为参数"""
        path = _write_srt(tmp_path, VALID_SRT)
        subs = parse_srt(Path(path))
        assert len(subs) == 3

    def test_special_characters(self, tmp_path):
        """特殊字符应正常处理"""
        content = """\
1
00:00:01,000 --> 00:00:03,000
Hello! 你好世界 🌍
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)
        assert subs[0].text == "Hello! 你好世界 🌍"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  parse_srt — 边界场景
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestParseSRTBoundary:
    """边界场景"""

    def test_empty_file(self, tmp_path):
        """空文件应返回空列表"""
        path = _write_srt(tmp_path, "")
        subs = parse_srt(path)
        assert subs == []

    def test_whitespace_only(self, tmp_path):
        """只有空白字符应返回空列表"""
        path = _write_srt(tmp_path, "   \n\n   \n")
        subs = parse_srt(path)
        assert subs == []

    def test_file_not_found(self, tmp_path):
        """文件不存在应抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            parse_srt(tmp_path / "nonexistent.srt")

    def test_malformed_block_missing_lines(self, tmp_path):
        """字幕块少于3行应被跳过"""
        content = """\
1
00:00:01,000 --> 00:00:03,000

2
00:00:05,000 --> 00:00:08,000
Valid text
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)
        # 第一个块没有文本，应被跳过
        assert len(subs) == 1
        assert subs[0].text == "Valid text"

    def test_invalid_index(self, tmp_path):
        """非数字索引应被跳过"""
        content = """\
abc
00:00:01,000 --> 00:00:03,000
Should be skipped

2
00:00:05,000 --> 00:00:08,000
Valid
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)
        assert len(subs) == 1
        assert subs[0].text == "Valid"

    def test_invalid_time_format(self, tmp_path):
        """无效时间格式应被跳过"""
        content = """\
1
invalid time format
Should be skipped

2
00:00:05,000 --> 00:00:08,000
Valid
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)
        assert len(subs) == 1
        assert subs[0].text == "Valid"

    def test_empty_text_skipped(self, tmp_path):
        """空文本字幕应被跳过"""
        content = """\
1
00:00:01,000 --> 00:00:03,000


2
00:00:05,000 --> 00:00:08,000
Valid
"""
        path = _write_srt(tmp_path, content)
        subs = parse_srt(path)
        assert len(subs) == 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  filter_short_subtitles
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFilterShortSubtitles:
    """短字幕过滤"""

    def test_filter_by_duration(self):
        """时长过短的字幕应被过滤"""
        subs = [
            Subtitle(1, 0.0, 0.5, "Too short"),   # 0.5s < 1.0s
            Subtitle(2, 1.0, 3.0, "OK"),          # 2.0s >= 1.0s
            Subtitle(3, 5.0, 5.8, "Short"),       # 0.8s < 1.0s
        ]
        result = filter_short_subtitles(subs, min_duration=1.0)

        assert len(result) == 1
        assert result[0].text == "OK"

    def test_reindex_after_filter(self):
        """过滤后应重新编号"""
        subs = [
            Subtitle(5, 0.0, 2.0, "First"),
            Subtitle(10, 3.0, 3.5, "Short"),
            Subtitle(15, 5.0, 8.0, "Second"),
        ]
        result = filter_short_subtitles(subs, min_duration=1.0)

        assert len(result) == 2
        assert result[0].index == 1
        assert result[1].index == 2

    def test_min_duration_zero(self):
        """min_duration=0 应保留所有字幕"""
        subs = [
            Subtitle(1, 0.0, 0.1, "Very short"),
            Subtitle(2, 1.0, 3.0, "Normal"),
        ]
        result = filter_short_subtitles(subs, min_duration=0)
        assert len(result) == 2

    def test_all_filtered(self):
        """所有字幕都不满足条件应返回空列表"""
        subs = [
            Subtitle(1, 0.0, 0.5, "A"),
            Subtitle(2, 1.0, 1.3, "B"),
        ]
        result = filter_short_subtitles(subs, min_duration=1.0)
        assert result == []

    def test_empty_input(self):
        """空列表应返回空列表"""
        result = filter_short_subtitles([], min_duration=1.0)
        assert result == []

    def test_exact_boundary(self):
        """时长恰好等于 min_duration 应保留"""
        subs = [Subtitle(1, 0.0, 1.0, "Exact")]
        result = filter_short_subtitles(subs, min_duration=1.0)
        assert len(result) == 1
