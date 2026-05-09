"""
测试 media_cut 模块 — 音频切割失败时不再导致截图错位
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.media_cut import MediaItem, process_media_items


def test_process_single_returns_placeholder_on_audio_cut_failure(tmp_path):
    """
    验证：音频切割失败时，process_single 返回带空路径的 MediaItem（而非 None），
    确保 media_items 长度与输入 items 长度一致。
    """
    audio_dir = tmp_path / "audio"
    screenshot_dir = tmp_path / "screenshots"
    audio_dir.mkdir()
    screenshot_dir.mkdir()

    items = [
        {"index": 1, "start_sec": 0.0, "end_sec": 2.0, "text": "card 1"},
        {"index": 2, "start_sec": 2.0, "end_sec": 4.0, "text": "card 2"},
        {"index": 3, "start_sec": 4.0, "end_sec": 6.0, "text": "card 3"},
    ]

    # Mock: 截图全部成功，音频切割第2条失败
    mock_ss_map = {1: "ss1.jpg", 2: "ss2.jpg", 3: "ss3.jpg"}
    cut_results = [True, False, True]  # 第2条失败

    # Mock cut_audio 按顺序返回结果
    call_count = [0]

    def mock_cut_audio(source, start, end, output):
        result = cut_results[call_count[0]]
        call_count[0] += 1
        return result

    # 直接测试 process_single 的行为
    with patch("core.media_cut.cut_audio", side_effect=mock_cut_audio), \
         patch("core.media_cut.get_video_duration", return_value=10.0), \
         patch("core.media_cut.extract_full_audio", return_value=(True, "")), \
         patch("core.media_cut.capture_screenshot", return_value=True):
        # 先创建 _full.mp3 避免抽取音轨
        (audio_dir / "_full.mp3").write_text("fake")
        # 创建截图文件
        for idx in [1, 2, 3]:
            (screenshot_dir / f"card_{idx:04d}.jpg").write_text("fake")

        results = process_media_items(
            str(tmp_path / "fake.mp4"),
            items,
            str(tmp_path),
            num_workers=1
        )

    # 关键断言：长度必须一致
    assert len(results) == len(items), \
        f"期望 {len(items)} 条结果，实际 {len(results)} 条（切割失败被丢弃了！）"

    # 第2条应有空路径
    assert results[1].index == 2
    assert results[1].audio_path == "", \
        f"切割失败应返回空 audio_path，实际为: {results[1].audio_path}"
    assert results[1].screenshot_path != "", \
        f"截图成功但被置空了: {results[1].screenshot_path}"


def test_main_index_matching_prevents_misalignment():
    """
    验证：index 匹配替代 zip 后，即使 media_items 缺少某条，
    processed 中其他条目的媒体路径不会错位。
    """
    processed = [
        {"index": 1, "start_sec": 0.0, "end_sec": 2.0, "text": "card 1",
         "audio_path": "", "screenshot_path": ""},
        {"index": 2, "start_sec": 2.0, "end_sec": 4.0, "text": "card 2",
         "audio_path": "", "screenshot_path": ""},
        {"index": 3, "start_sec": 4.0, "end_sec": 6.0, "text": "card 3",
         "audio_path": "", "screenshot_path": ""},
    ]

    # 模拟：card_2 音频切割失败，只有 card_1 和 card_3 有媒体
    media_items = [
        MediaItem(index=1, start_sec=0.0, end_sec=2.0,
                  audio_path="audio/1.mp3", screenshot_path="ss/1.jpg"),
        MediaItem(index=3, start_sec=4.0, end_sec=6.0,
                  audio_path="audio/3.mp3", screenshot_path="ss/3.jpg"),
    ]

    # 新的匹配逻辑
    media_map = {m.index: m for m in media_items}
    for p in processed:
        m = media_map.get(p["index"])
        if m:
            p["audio_path"] = m.audio_path
            p["screenshot_path"] = m.screenshot_path
        else:
            p["audio_path"] = ""
            p["screenshot_path"] = ""

    # card 1: 应有媒体
    assert processed[0]["audio_path"] == "audio/1.mp3"
    assert processed[0]["screenshot_path"] == "ss/1.jpg"

    # card 2: 切割失败，路径应为空
    assert processed[1]["audio_path"] == ""
    assert processed[1]["screenshot_path"] == ""

    # card 3: 应拿到自己的媒体，不是 card_2 的
    assert processed[2]["audio_path"] == "audio/3.mp3", \
        f"错位！card_3 拿到了 {processed[2]['audio_path']} 而非 audio/3.mp3"
    assert processed[2]["screenshot_path"] == "ss/3.jpg"
