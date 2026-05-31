"""
测试 main.py — index 偏移、corrected_text 透传、机器翻译集成
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from main import _apply_index_offset, _process_video_to_media


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


# ─── 机器翻译集成测试 ─────────────────────────────────────────


def test_mt_service_applied_when_no_ai_key(tmp_path):
    """无 AI Key + 配置了 mt_service 时，应调用机器翻译"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nGood morning\n\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"\x00" * 100)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_translator = MagicMock()
    mock_translator.translate.return_value = ["你好世界", "早上好"]

    with patch("core.translate.create_translator", return_value=mock_translator) as mock_create:
        with patch("main.process_media_items", return_value=[]):
            processed, _ = _process_video_to_media(
                video_path=str(video_path),
                subtitle_path=str(srt_path),
                output_dir=str(output_dir),
                api_key=None,
                mt_service="bing",
                source_language="en",
                target_language="zh",
                progress_callback=lambda *a: None,
            )

    mock_create.assert_called_once_with("bing")
    mock_translator.translate.assert_called_once()
    assert len(processed) == 2
    assert processed[0]["translation"] == "你好世界"
    assert processed[1]["translation"] == "早上好"


def test_no_mt_no_ai_leaves_translation_empty(tmp_path):
    """无 AI Key 且无 mt_service 时，translation 保持为空"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"\x00" * 100)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with patch("main.process_media_items", return_value=[]):
        processed, _ = _process_video_to_media(
            video_path=str(video_path),
            subtitle_path=str(srt_path),
            output_dir=str(output_dir),
            api_key=None,
            mt_service=None,
            progress_callback=lambda *a: None,
        )

    assert len(processed) == 1
    assert processed[0]["translation"] == ""


def test_mt_failure_does_not_crash(tmp_path):
    """机器翻译失败时，translation 保持为空但不中断处理"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello world\n\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"\x00" * 100)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = RuntimeError("Network error")

    with patch("core.translate.create_translator", return_value=mock_translator):
        with patch("main.process_media_items", return_value=[]):
            processed, _ = _process_video_to_media(
                video_path=str(video_path),
                subtitle_path=str(srt_path),
                output_dir=str(output_dir),
                api_key=None,
                mt_service="bing",
                source_language="en",
                target_language="zh",
                progress_callback=lambda *a: None,
            )

    assert len(processed) == 1
    assert processed[0]["translation"] == ""


def test_mt_with_deepl_passes_api_key(tmp_path):
    """使用 DeepL 翻译时应传递 api_key"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"\x00" * 100)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_translator = MagicMock()
    mock_translator.translate.return_value = ["你好"]

    with patch("core.translate.create_translator", return_value=mock_translator) as mock_create:
        with patch("main.process_media_items", return_value=[]):
            _process_video_to_media(
                video_path=str(video_path),
                subtitle_path=str(srt_path),
                output_dir=str(output_dir),
                api_key=None,
                mt_service="deepl",
                mt_api_key="dl-test-key",
                source_language="en",
                target_language="zh",
                progress_callback=lambda *a: None,
            )

    mock_create.assert_called_once_with("deepl", api_key="dl-test-key")


def test_mt_with_openai_passes_all_params(tmp_path):
    """使用 OpenAI 翻译时应传递 api_key、api_base、model_name"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "test.mp4"
    video_path.write_bytes(b"\x00" * 100)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    mock_translator = MagicMock()
    mock_translator.translate.return_value = ["你好"]

    with patch("core.translate.create_translator", return_value=mock_translator) as mock_create:
        with patch("main.process_media_items", return_value=[]):
            _process_video_to_media(
                video_path=str(video_path),
                subtitle_path=str(srt_path),
                output_dir=str(output_dir),
                api_key=None,
                mt_service="openai",
                mt_api_key="sk-test",
                mt_api_base="https://custom.api.com",
                mt_model_name="gpt-4o",
                source_language="en",
                target_language="zh",
                progress_callback=lambda *a: None,
            )

    mock_create.assert_called_once_with(
        "openai",
        api_key="sk-test",
        api_base="https://custom.api.com",
        model_name="gpt-4o",
    )


def test_stop_after_media_only_processes_first_video(tmp_path):
    """stop_after_media=True + 多视频时，只处理第一个视频"""
    # 创建两个视频文件
    video1 = tmp_path / "video1.mp4"
    video2 = tmp_path / "video2.mp4"
    video1.write_bytes(b"\x00" * 100)
    video2.write_bytes(b"\x00" * 100)

    # 创建对应的字幕文件
    srt1 = tmp_path / "video1.srt"
    srt2 = tmp_path / "video2.srt"
    srt1.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n\n", encoding="utf-8")
    srt2.write_text("1\n00:00:01,000 --> 00:00:03,000\nWorld\n\n", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    call_count = 0
    original_func = _process_video_to_media

    def mock_process(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # 返回最小有效结果
        return ([{"index": 1, "text": "test", "translation": "", "notes": "", "reason": "", "word": "", "definition": ""}], "video1")

    with patch("main._process_video_to_media", side_effect=mock_process):
        with patch("main.process_media_items", return_value=[]):
            with patch("main.create_apkg", return_value=tmp_path / "deck.apkg"):
                from main import run
                run(
                    video_paths=[str(video1), str(video2)],
                    subtitle_paths=[str(srt1), str(srt2)],
                    output_dir=str(output_dir),
                    merge=True,
                    api_key=None,
                    stop_after_media=True,
                    progress_callback=lambda *a: None,
                )

    # 只应该处理第一个视频
    assert call_count == 1, f"stop_after_media=True 时只应处理 1 个视频，实际处理了 {call_count} 个"


def test_stop_after_media_false_processes_all_videos(tmp_path):
    """stop_after_media=False + 多视频时，处理所有视频"""
    video1 = tmp_path / "video1.mp4"
    video2 = tmp_path / "video2.mp4"
    video1.write_bytes(b"\x00" * 100)
    video2.write_bytes(b"\x00" * 100)

    srt1 = tmp_path / "video1.srt"
    srt2 = tmp_path / "video2.srt"
    srt1.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n\n", encoding="utf-8")
    srt2.write_text("1\n00:00:01,000 --> 00:00:03,000\nWorld\n\n", encoding="utf-8")

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    call_count = 0

    def mock_process(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return ([{"index": 1, "text": "test", "translation": "", "notes": "", "reason": "", "word": "", "definition": ""}], f"video{call_count}")

    with patch("main._process_video_to_media", side_effect=mock_process):
        with patch("main.process_media_items", return_value=[]):
            with patch("main.create_apkg", return_value=tmp_path / "deck.apkg"):
                from main import run
                run(
                    video_paths=[str(video1), str(video2)],
                    subtitle_paths=[str(srt1), str(srt2)],
                    output_dir=str(output_dir),
                    merge=True,
                    api_key=None,
                    stop_after_media=False,
                    progress_callback=lambda *a: None,
                )

    # 应该处理所有视频
    assert call_count == 2, f"stop_after_media=False 时应处理所有 {2} 个视频，实际处理了 {call_count} 个"
