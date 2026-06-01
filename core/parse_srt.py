"""
字幕解析模块 - 解析 .srt 文件，提取时间轴和文本
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
from errors import ClipLingoError, ErrorCode


@dataclass
class Subtitle:
    """单条字幕"""
    index: int          # 字幕序号
    start_sec: float    # 开始时间（秒）
    end_sec: float      # 结束时间（秒）
    text: str           # 字幕文本（多行合并）


def parse_time_to_seconds(time_str: str) -> float:
    """
    将 SRT 时间格式转为秒
    格式: 00:00:00,000 -> 0.0
    """
    # 移除逗号改为点
    time_str = time_str.replace(',', '.')
    parts = time_str.strip().split(':')

    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])

    return hours * 3600 + minutes * 60 + seconds


def parse_srt(file_path: str | Path) -> list[Subtitle]:
    """
    解析 .srt 文件

    Args:
        file_path: .srt 文件路径

    Returns:
        Subtitle 对象列表
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"字幕文件不存在: {path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError as e:
        raise ClipLingoError(
            ErrorCode.SUBTITLE_PARSE_FAILED,
            f"字幕文件不是 UTF-8 编码，请转换后重试: {e}"
        ) from e

    subtitles = []
    # 分割每条字幕块
    blocks = re.split(r'\n\n+', content.strip())

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue

        # 第1行: 序号
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # 第2行: 时间轴 -> 00:00:00,000 --> 00:00:00,000
        time_line = lines[1]
        time_match = re.search(
            r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})',
            time_line
        )
        if not time_match:
            continue

        start_time = parse_time_to_seconds(time_match.group(1))
        end_time = parse_time_to_seconds(time_match.group(2))

        # 第3行开始: 字幕文本（合并多行）
        text = ' '.join(line.strip() for line in lines[2:] if line.strip())

        if text:  # 只保留有文本的字幕
            subtitles.append(Subtitle(
                index=index,
                start_sec=start_time,
                end_sec=end_time,
                text=text
            ))

    # 重新编号为连续序号（SRT 文件编号可能有缺口）
    for i, sub in enumerate(subtitles):
        sub.index = i + 1

    return subtitles


def filter_short_subtitles(subtitles: list[Subtitle], min_duration: float = 1.0) -> list[Subtitle]:
    """
    过滤时长过短的字幕

    Args:
        subtitles: 字幕列表
        min_duration: 最短时长（秒），默认1秒

    Returns:
        过滤后的列表
    """
    filtered = [s for s in subtitles if (s.end_sec - s.start_sec) >= min_duration]

    # 过滤后重新编号为连续序号
    for i, sub in enumerate(filtered):
        sub.index = i + 1

    return filtered


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        subs = parse_srt(sys.argv[1])
        for s in subs[:5]:
            print(f"[{s.start_sec:.2f}s - {s.end_sec:.2f}s] {s.text}")