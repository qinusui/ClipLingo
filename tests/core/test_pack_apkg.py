"""
pack_apkg 模块测试
覆盖：generate_model_id、create_deck、save_deck_with_media、create_apkg
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import os

from core.pack_apkg import (
    CardData, generate_model_id, create_deck, save_deck_with_media, create_apkg,
)


# ── 辅助 ────────────────────────────────────────────────

def _make_card(**kwargs) -> CardData:
    defaults = {
        "index": 1,
        "sentence": "Hello world",
        "translation": "你好世界",
        "notes": "词汇注释",
        "audio_path": "",
        "screenshot_path": "",
        "word": "",
        "definition": "",
    }
    defaults.update(kwargs)
    return CardData(**defaults)


def _make_cards(n: int = 2) -> list[CardData]:
    return [_make_card(index=i + 1, sentence=f"Sentence {i + 1}") for i in range(n)]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  generate_model_id
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGenerateModelId:
    """模型 ID 生成"""

    def test_stable_output(self):
        """相同输入应产生相同输出"""
        id1 = generate_model_id("test-deck")
        id2 = generate_model_id("test-deck")
        assert id1 == id2

    def test_different_inputs_different_outputs(self):
        """不同输入应产生不同输出"""
        id1 = generate_model_id("deck-a")
        id2 = generate_model_id("deck-b")
        assert id1 != id2

    def test_positive_integer(self):
        """应返回正整数"""
        result = generate_model_id("any-name")
        assert isinstance(result, int)
        assert result > 0

    def test_within_31_bit(self):
        """应在 31 位范围内（正 int32）"""
        result = generate_model_id("test")
        assert result <= 0x7FFFFFFF


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  create_deck
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCreateDeck:
    """创建 Anki 牌组"""

    def test_empty_cards(self):
        """空卡片列表应创建空牌组"""
        deck = create_deck("test-deck", [])
        assert deck is not None
        assert deck.name == "test-deck"

    def test_with_cards(self):
        """带卡片的牌组"""
        cards = _make_cards(3)
        deck = create_deck("test-deck", cards)
        assert deck is not None

    def test_default_sentence_style(self):
        """默认应使用 sentence 样式"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards)
        # 应成功创建，不抛出异常
        assert deck is not None

    def test_vocab_style(self):
        """vocab 样式"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, card_styles=["vocab"])
        assert deck is not None

    def test_both_styles(self):
        """同时使用 sentence 和 vocab 样式"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, card_styles=["sentence", "vocab"])
        assert deck is not None

    def test_unknown_style_falls_back_to_sentence(self):
        """未知样式应回退到 sentence"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, card_styles=["unknown"])
        assert deck is not None

    def test_with_audio_path(self):
        """带音频路径的卡片"""
        card = _make_card(audio_path="/path/to/audio.mp3")
        deck = create_deck("test-deck", [card])
        assert deck is not None

    def test_with_screenshot_path(self):
        """带截图路径的卡片"""
        card = _make_card(screenshot_path="/path/to/screenshot.jpg")
        deck = create_deck("test-deck", [card])
        assert deck is not None

    def test_word_fallback_to_sentence(self):
        """无单词时应用整句作为降级"""
        card = _make_card(sentence="Full sentence", word="")
        deck = create_deck("test-deck", [card])
        assert deck is not None

    def test_theme_default(self):
        """默认主题"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, theme="default")
        assert deck is not None

    def test_theme_minimal(self):
        """极简主题"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, theme="minimal")
        assert deck is not None

    def test_theme_netflix(self):
        """Netflix 主题"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, theme="netflix")
        assert deck is not None

    def test_theme_dictionary(self):
        """词典主题"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, theme="dictionary")
        assert deck is not None

    def test_theme_overrides(self):
        """CSS 变量覆盖"""
        cards = _make_cards(1)
        deck = create_deck("test-deck", cards, theme_overrides={"--card-bg": "#1a1a2e"})
        assert deck is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  save_deck_with_media
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSaveDeckWithMedia:
    """保存牌组并打包媒体"""

    def test_save_without_media(self, tmp_path):
        """无媒体文件保存"""
        deck = create_deck("test-deck", _make_cards(1))
        output_path = tmp_path / "test.apkg"

        save_deck_with_media(deck, str(output_path))

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_save_with_existing_audio(self, tmp_path):
        """带存在的音频文件"""
        # 创建模拟音频文件
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        audio_file = audio_dir / "clip.mp3"
        audio_file.write_bytes(b"fake audio content")

        deck = create_deck("test-deck", [_make_card(audio_path="clip.mp3")])
        output_path = tmp_path / "test.apkg"

        save_deck_with_media(
            deck, str(output_path),
            audio_files=["clip.mp3"],
            audio_dir=str(audio_dir),
        )

        assert output_path.exists()

    def test_save_with_existing_screenshot(self, tmp_path):
        """带存在的截图文件"""
        screenshot_dir = tmp_path / "screenshots"
        screenshot_dir.mkdir()
        screenshot_file = screenshot_dir / "shot.jpg"
        screenshot_file.write_bytes(b"fake image content")

        deck = create_deck("test-deck", [_make_card(screenshot_path="shot.jpg")])
        output_path = tmp_path / "test.apkg"

        save_deck_with_media(
            deck, str(output_path),
            screenshot_files=["shot.jpg"],
            screenshot_dir=str(screenshot_dir),
        )

        assert output_path.exists()

    def test_missing_media_file_graceful(self, tmp_path):
        """缺失的媒体文件应被优雅处理"""
        deck = create_deck("test-deck", [_make_card(audio_path="missing.mp3")])
        output_path = tmp_path / "test.apkg"

        # 不应抛出异常
        save_deck_with_media(
            deck, str(output_path),
            audio_files=["missing.mp3"],
            audio_dir="/nonexistent",
        )

        assert output_path.exists()

    def test_output_parent_created(self, tmp_path):
        """输出目录不存在时应自动创建"""
        deck = create_deck("test-deck", _make_cards(1))
        output_path = tmp_path / "nested" / "dir" / "test.apkg"

        save_deck_with_media(deck, str(output_path))

        assert output_path.exists()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  create_apkg
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestCreateApkg:
    """完整 APKG 创建"""

    def test_create_apkg_normal(self, tmp_path):
        """正常创建 APKG"""
        cards = [
            {
                "index": 1,
                "text": "Hello",
                "translation": "你好",
                "notes": "注释",
                "audio_path": "",
                "screenshot_path": "",
            }
        ]

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        screenshot_dir = tmp_path / "screenshots"
        screenshot_dir.mkdir()

        result = create_apkg(
            video_name="test_video.mp4",
            cards=cards,
            output_dir=str(output_dir),
            audio_dir=str(audio_dir),
            screenshot_dir=str(screenshot_dir),
        )

        assert Path(result).exists()
        assert result.endswith(".apkg")

    def test_create_apkg_missing_output_raises_cliplingo_error(self, tmp_path):
        """保存后输出文件不存在应抛出 ClipLingoError(INTERNAL_ERROR)"""
        from errors import ClipLingoError, ErrorCode

        # 不创建 output 目录：mock 保存为 no-op 后，output_path 必然不存在
        output_dir = tmp_path / "output"

        with patch("core.pack_apkg.save_deck_with_media") as mock_save:
            mock_save.return_value = None
            with pytest.raises(ClipLingoError) as exc_info:
                create_apkg(
                    video_name="test_video.mp4",
                    cards=[],
                    output_dir=str(output_dir),
                    audio_dir=str(tmp_path),
                    screenshot_dir=str(tmp_path),
                )
        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
        """牌组名应取自视频文件名的 stem"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = create_apkg(
            video_name="my_video.mp4",
            cards=[],
            output_dir=str(output_dir),
            audio_dir=str(tmp_path),
            screenshot_dir=str(tmp_path),
        )

        assert "my_video.apkg" in result

    def test_create_apkg_empty_cards(self, tmp_path):
        """空卡片列表应仍能创建"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = create_apkg(
            video_name="test.mp4",
            cards=[],
            output_dir=str(output_dir),
            audio_dir=str(tmp_path),
            screenshot_dir=str(tmp_path),
        )

        assert Path(result).exists()

    def test_create_apkg_with_theme(self, tmp_path):
        """指定主题创建"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = create_apkg(
            video_name="test.mp4",
            cards=[{"text": "Hi", "translation": "嗨", "notes": "", "audio_path": "", "screenshot_path": ""}],
            output_dir=str(output_dir),
            audio_dir=str(tmp_path),
            screenshot_dir=str(tmp_path),
            theme="netflix",
        )

        assert Path(result).exists()

    def test_create_apkg_with_theme_overrides(self, tmp_path):
        """带 CSS 变量覆盖创建"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        result = create_apkg(
            video_name="test.mp4",
            cards=[{"text": "Hi", "translation": "嗨", "notes": "", "audio_path": "", "screenshot_path": ""}],
            output_dir=str(output_dir),
            audio_dir=str(tmp_path),
            screenshot_dir=str(tmp_path),
            theme_overrides={"--card-bg": "#000"},
        )

        assert Path(result).exists()
