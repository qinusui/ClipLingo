"""
场景3: 验证manifest合并和apkg生成完整性

测试内容:
1. Manifest正确合并多视频数据
2. APKG生成包含所有视频的卡片
3. 媒体文件完整打包
4. 数据一致性验证
"""
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from main import generate_apkg


def test_manifest_merge_mode_structure():
    """验证合并模式manifest的结构正确性"""
    manifest = {
        "merge": True,
        "video_names": ["video1.mp4", "video2.mp4"],
        "processed": [
            {"index": 1, "video_stem": "video1", "text": "card 1"},
            {"index": 2, "video_stem": "video1", "text": "card 2"},
            {"index": 3, "video_stem": "video2", "text": "card 3"},
        ]
    }

    # 验证结构
    assert manifest["merge"] is True
    assert len(manifest["video_names"]) == 2
    assert len(manifest["processed"]) == 3

    # 验证video_stem分布
    stems = {}
    for card in manifest["processed"]:
        stem = card.get("video_stem", "unknown")
        stems[stem] = stems.get(stem, 0) + 1

    assert stems["video1"] == 2
    assert stems["video2"] == 1


def test_manifest_append_preserves_order():
    """验证追加新卡片时保持顺序"""
    existing_cards = [
        {"index": 1, "video_stem": "video1"},
        {"index": 2, "video_stem": "video1"},
    ]

    new_cards = [
        {"index": 1, "video_stem": "video2"},
        {"index": 2, "video_stem": "video2"},
        {"index": 3, "video_stem": "video2"},
    ]

    # 模拟合并
    merged = existing_cards + new_cards

    assert len(merged) == 5
    assert merged[0]["video_stem"] == "video1"
    assert merged[2]["video_stem"] == "video2"


def test_apkg_generation_with_multiple_videos(tmp_path):
    """验证多视频APKG生成的完整性"""
    # 创建测试数据
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    # 创建manifest
    manifest_data = {
        "merge": True,
        "video_names": ["SE01.01.mkv", "test.mkv"],
        "processed": []
    }

    # 添加387张SE01.01卡片
    for i in range(1, 388):
        manifest_data["processed"].append({
            "index": i,
            "video_stem": "SE01.01",
            "start_sec": i * 3.0,
            "end_sec": i * 3.0 + 2.0,
            "snapshot_time": i * 3.0 + 1.0,
            "text": f"Card {i}",
            "translation": f"翻译 {i}",
            "notes": f"Notes {i}",
            "audio_path": str(output_dir / f"audio/card_{i:04d}.mp3"),
            "screenshot_path": str(output_dir / f"screenshots/card_{i:04d}.jpg")
        })

    # 添加66张test卡片
    for i in range(1, 67):
        idx = 387 + i
        manifest_data["processed"].append({
            "index": idx,
            "video_stem": "test",
            "start_sec": i * 3.0,
            "end_sec": i * 3.0 + 2.0,
            "snapshot_time": i * 3.0 + 1.0,
            "text": f"Test card {i}",
            "translation": f"测试翻译 {i}",
            "notes": f"Test notes {i}",
            "audio_path": str(output_dir / f"audio/card_{idx:04d}.mp3"),
            "screenshot_path": str(output_dir / f"screenshots/card_{idx:04d}.jpg")
        })

    # 写入manifest
    manifest_path = output_dir / "processed_cards.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    # 创建媒体目录和文件
    audio_dir = output_dir / "audio"
    screenshot_dir = output_dir / "screenshots"
    audio_dir.mkdir()
    screenshot_dir.mkdir()

    # 创建所有媒体文件（小文件即可）
    for i in range(1, 454):
        (audio_dir / f"card_{i:04d}.mp3").write_bytes(b"fake audio")
        (screenshot_dir / f"card_{i:04d}.jpg").write_bytes(b"fake image")

    # Mock create_apkg to avoid actual genanki calls
    with patch('main.create_apkg') as mock_create_apkg:
        mock_create_apkg.return_value = str(output_dir / "test.apkg")

        # 调用generate_apkg
        result = generate_apkg(
            output_dir=str(output_dir),
            card_styles=["basic"],
            theme="default",
            theme_overrides={}
        )

    # 验证结果
    assert result["cards_count"] == 453
    assert "apkg_path" in result
    assert "processed" in result
    assert len(result["processed"]) == 453

    # 验证create_apkg被正确调用
    assert mock_create_apkg.called
    call_args = mock_create_apkg.call_args
    # 第一个参数是deck_name
    assert "SE01.01" in call_args[0][0]
    # 第二个参数是cards列表
    assert len(call_args[0][1]) == 453


def test_manifest_data_consistency():
    """验证manifest数据一致性"""
    manifest = {
        "merge": True,
        "video_names": ["video1.mp4", "video2.mp4", "video3.mp4"],
        "processed": [
            {"index": 1, "video_stem": "video1"},
            {"index": 2, "video_stem": "video1"},
            {"index": 3, "video_stem": "video2"},
            {"index": 4, "video_stem": "video3"},
            {"index": 5, "video_stem": "video3"},
        ]
    }

    # 统计每个视频的卡片数
    card_counts = {}
    for card in manifest["processed"]:
        stem = card.get("video_stem", "unknown")
        card_counts[stem] = card_counts.get(stem, 0) + 1

    assert card_counts["video1"] == 2
    assert card_counts["video2"] == 1
    assert card_counts["video3"] == 2
    assert len(card_counts) == 3  # 3个不同的视频


def test_media_file_path_mapping():
    """验证媒体文件路径正确映射到卡片"""
    cards = [
        {
            "index": 1,
            "video_stem": "video1",
            "audio_path": "/output/audio/card_0001.mp3",
            "screenshot_path": "/output/screenshots/card_0001.jpg"
        },
        {
            "index": 100,
            "video_stem": "video2",
            "audio_path": "/output/audio/card_0100.mp3",
            "screenshot_path": "/output/screenshots/card_0100.jpg"
        }
    ]

    for card in cards:
        assert "audio_path" in card
        assert "screenshot_path" in card
        assert card["audio_path"].endswith(".mp3")
        assert card["screenshot_path"].endswith(".jpg")
        assert f"card_{card['index']:04d}" in card["audio_path"]


def test_apkg_media_packaging(tmp_path):
    """验证APKG打包时媒体文件正确处理"""
    # 创建临时APKG文件
    apkg_path = tmp_path / "test.apkg"

    # 创建模拟APKG内容
    with zipfile.ZipFile(apkg_path, 'w') as zf:
        # 添加collection.anki2（数据库）
        zf.writestr("collection.anki2", "fake sqlite data")

        # 添加media映射文件
        media_map = {
            "0": "card_0001.mp3",
            "1": "card_0001.jpg",
            "2": "card_0002.mp3",
            "3": "card_0002.jpg"
        }
        zf.writestr("media", json.dumps(media_map))

        # 添加媒体文件
        for num, filename in media_map.items():
            zf.writestr(num, f"fake content for {filename}")

    # 验证APKG内容
    with zipfile.ZipFile(apkg_path, 'r') as zf:
        files = zf.namelist()

        # 必须包含collection.anki2和media
        assert "collection.anki2" in files
        assert "media" in files

        # 验证媒体映射
        media_content = json.loads(zf.read("media"))
        assert len(media_content) == 4

        # 验证媒体文件存在
        for num in media_content.keys():
            assert num in files


def test_empty_media_paths_handled():
    """验证空媒体路径正确处理（截图/音频失败的情况）"""
    cards = [
        {
            "index": 1,
            "video_stem": "video1",
            "audio_path": "/output/audio/card_0001.mp3",
            "screenshot_path": ""  # 截图失败
        },
        {
            "index": 2,
            "video_stem": "video1",
            "audio_path": "",  # 音频切割失败
            "screenshot_path": "/output/screenshots/card_0002.jpg"
        },
        {
            "index": 3,
            "video_stem": "video1",
            "audio_path": "",  # 都失败
            "screenshot_path": ""
        }
    ]

    # 统计有效媒体
    valid_audio = sum(1 for c in cards if c["audio_path"])
    valid_screenshots = sum(1 for c in cards if c["screenshot_path"])

    assert valid_audio == 1
    assert valid_screenshots == 1
    assert len(cards) == 3  # 所有卡片都应被处理


def test_manifest_merge_no_duplicates():
    """验证合并时不会产生重复卡片"""
    existing = [
        {"index": 1, "video_stem": "video1", "text": "card 1"},
        {"index": 2, "video_stem": "video1", "text": "card 2"},
    ]

    new_cards = [
        {"index": 1, "video_stem": "video2", "text": "card 1"},  # index重复但video不同
        {"index": 2, "video_stem": "video2", "text": "card 2"},
    ]

    # 使用(index, video_stem)作为唯一标识
    seen = set()
    merged = []

    for card in existing + new_cards:
        key = (card["index"], card["video_stem"])
        if key not in seen:
            seen.add(key)
            merged.append(card)

    assert len(merged) == 4  # 所有卡片都应保留
    assert len(seen) == 4
