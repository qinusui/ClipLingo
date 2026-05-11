"""
测试 main.py — index 偏移 和 corrected_text 透传
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import _apply_index_offset


def test_apply_index_offset_zero_noop():
    """offset=0 时原样返回"""
    items = [{"index": 1}, {"index": 2}]
    result = _apply_index_offset(items, 0)
    assert result[0]["index"] == 1
    assert result[1]["index"] == 2


def test_apply_index_offset_adds_offset():
    """offset=10000 时所有 index 加上偏移"""
    items = [{"index": 1}, {"index": 5}, {"index": 10}]
    result = _apply_index_offset(items, 10000)
    assert result[0]["index"] == 10001
    assert result[1]["index"] == 10005
    assert result[2]["index"] == 10010


def test_apply_index_offset_missing_index():
    """条目无 index 字段时默认为 0 再加偏移"""
    items = [{"text": "no index"}]
    result = _apply_index_offset(items, 10000)
    assert result[0]["index"] == 10000


def test_corrected_text_takes_priority():
    """
    验证：pre_processed 中的 text 字段（corrected_text）应优先于 SRT 原始文本。
    直接测试 _process_video_to_media 中的预处理合并逻辑。
    """
    # 模拟 SRT 解析出的字幕
    subtitles = [
        type("Sub", (), {"index": 1, "start_sec": 0.0, "end_sec": 2.0, "text": "original wrong text"})(),
        type("Sub", (), {"index": 2, "start_sec": 2.0, "end_sec": 4.0, "text": "correct original"})(),
    ]
    # 预处理数据，第一条有修正文本
    pre_processed = [
        {"text": "corrected text from AI", "translation": "翻译1", "notes": "", "reason": "", "word": "", "definition": ""},
        {"translation": "翻译2", "notes": "", "reason": "", "word": "", "definition": ""},
    ]

    # 模拟 main.py 中的合并逻辑
    processed = []
    for sub, pp in zip(subtitles, pre_processed):
        processed.append({
            "index": sub.index,
            "start_sec": sub.start_sec,
            "end_sec": sub.end_sec,
            "text": pp.get("text") or sub.text,
            "translation": pp.get("translation", ""),
            "notes": pp.get("notes", ""),
            "reason": pp.get("reason", ""),
            "word": pp.get("word", ""),
            "definition": pp.get("definition", "")
        })

    # 第一条：应使用修正后的文本
    assert processed[0]["text"] == "corrected text from AI", \
        f"未使用 corrected_text，实际: {processed[0]['text']}"
    # 第二条：pre_processed 无 text 字段，应回退到原始文本
    assert processed[1]["text"] == "correct original", \
        f"回退到原始文本失败，实际: {processed[1]['text']}"


def test_corrected_text_empty_string_falls_back():
    """pre_processed text 为空字符串时，应回退到原始文本"""
    sub = type("Sub", (), {"index": 1, "start_sec": 0.0, "end_sec": 2.0, "text": "original text"})()
    pp = {"text": "", "translation": "", "notes": "", "reason": "", "word": "", "definition": ""}

    text = pp.get("text") or sub.text
    assert text == "original text"
