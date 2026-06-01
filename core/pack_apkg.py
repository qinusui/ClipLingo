"""
打包模块 - 使用 genanki 生成可导入 Anki 的 .apkg 文件
"""

import genanki
import hashlib
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from core.templates import get_theme

_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)
from errors import ClipLingoError, ErrorCode


@dataclass
class CardData:
    """卡片数据"""
    index: int
    sentence: str
    translation: str
    notes: str
    audio_path: str
    screenshot_path: str
    word: str = ""
    definition: str = ""


def generate_model_id(name: str) -> int:
    """根据名称生成稳定的模型 ID"""
    hash_val = hashlib.md5(name.encode()).digest()
    return int.from_bytes(hash_val[:4], 'big') & 0x7FFFFFFF


def _create_model(model_id: int, name: str, templates: list[dict], css: str) -> genanki.Model:
    """创建统一字段的 Anki 模型"""
    return genanki.Model(
        model_id=model_id,
        name=name,
        fields=[
            {'name': 'Sentence'},
            {'name': 'Screenshot'},
            {'name': 'Audio'},
            {'name': 'Translation'},
            {'name': 'Notes'},
            {'name': 'Word'},
            {'name': 'Definition'},
        ],
        templates=templates,
        css=css
    )


def create_deck(
    deck_name: str,
    cards: list[CardData],
    card_styles: list[str] = None,
    audio_dir: str = None,
    screenshot_dir: str = None,
    theme: str = "default",
    theme_overrides: dict | None = None
) -> genanki.Deck:
    """
    创建 Anki 牌组

    Args:
        deck_name: 牌组名称
        cards: 卡片数据列表
        card_styles: 卡片样式列表，如 ["sentence"]、["vocab"]、["sentence", "vocab"]
        audio_dir: 音频目录
        screenshot_dir: 截图目录
        theme: 主题名称，可选 "default"、"minimal"、"netflix"、"dictionary"
        theme_overrides: CSS 变量覆盖字典，如 {"--card-bg": "#1a1a2e"}

    Returns:
        genanki.Deck 对象
    """
    if card_styles is None:
        card_styles = ["sentence"]

    theme_cfg = get_theme(theme, theme_overrides) or get_theme("default")
    css = theme_cfg["css"]

    # 根据选中的样式构建模板列表
    templates = []
    if "sentence" in card_styles:
        qfmt, afmt = theme_cfg["sentence"]
        templates.append({'name': '句型卡', 'qfmt': qfmt, 'afmt': afmt})
    if "vocab" in card_styles:
        qfmt, afmt = theme_cfg["vocab"]
        templates.append({'name': '词汇卡', 'qfmt': qfmt, 'afmt': afmt})

    if not templates:
        qfmt, afmt = theme_cfg["sentence"]
        templates.append({'name': '句型卡', 'qfmt': qfmt, 'afmt': afmt})

    model = _create_model(
        generate_model_id("ClipLingo_" + deck_name + "_" + theme),
        f'ClipLingo-{theme_cfg["name"]}',
        templates,
        css=css
    )

    deck = genanki.Deck(
        deck_id=generate_model_id(deck_name),
        name=deck_name
    )

    for card in cards:
        audio_name = os.path.basename(card.audio_path) if card.audio_path else ""
        screenshot_name = os.path.basename(card.screenshot_path) if card.screenshot_path else ""
        screenshot_field = f'<img src="{screenshot_name}">' if screenshot_name else ""
        audio_field = f'[sound:{audio_name}]' if audio_name else ""
        word = card.word or card.sentence  # 降级：无单词时用整句

        note = genanki.Note(
            model=model,
            fields=[
                card.sentence,      # Sentence（排序字段）
                screenshot_field,   # Screenshot
                audio_field,        # Audio
                card.translation,   # Translation
                card.notes,         # Notes
                word,               # Word
                card.definition,    # Definition
            ]
        )
        deck.add_note(note)

    return deck


def save_deck_with_media(
    deck: genanki.Deck,
    output_path: str,
    audio_files: list[str] = None,
    screenshot_files: list[str] = None,
    audio_dir: str = None,
    screenshot_dir: str = None
):
    """
    保存牌组并打包媒体文件

    Args:
        deck: genanki.Deck 对象
        output_path: 输出 .apkg 路径
        audio_files: 音频文件列表（完整路径）
        screenshot_files: 截图文件列表（完整路径）
        audio_dir: 音频源目录
        screenshot_dir: 截图源目录
    """
    # 创建临时目录存放媒体文件
    import tempfile
    import shutil

    temp_dir = Path(tempfile.mkdtemp())
    print(f"创建临时目录: {temp_dir}")

    # 复制媒体文件到临时目录
    copied_files = []

    def copy_to_media(filename: str, source_dir: str = None) -> str:
        if not filename:
            return None
        if source_dir:
            source = Path(source_dir) / filename
        else:
            source = Path(filename)

        if source.exists():
            dest = temp_dir / Path(filename).name
            shutil.copy2(source, dest)
            copied_files.append(str(dest))
            print(f"复制文件: {source} -> {dest}")
            return str(Path(filename).name)
        else:
            print(f"文件不存在: {source}")
            return None

    # 处理音频文件
    if audio_files:
        print(f"音频文件: {audio_files}")
        for af in audio_files:
            copy_to_media(os.path.basename(af), audio_dir)

    # 处理截图文件
    if screenshot_files:
        print(f"截图文件: {screenshot_files}")
        for sf in screenshot_files:
            copy_to_media(os.path.basename(sf), screenshot_dir)

    print(f"复制的媒体文件: {copied_files}")

    # 写入包文件
    package = genanki.Package(deck)
    package.media_files = copied_files

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"保存到: {output}")
    package.write_to_file(str(output))

    # 清理临时目录
    shutil.rmtree(temp_dir, ignore_errors=True)
    print(f"清理临时目录: {temp_dir}")


def create_apkg(
    video_name: str,
    cards: list[dict],
    output_dir: str,
    audio_dir: str,
    screenshot_dir: str,
    card_styles: list[str] = None,
    theme: str = "default",
    theme_overrides: dict | None = None
) -> str:
    """
    创建完整的 .apkg 文件

    Args:
        video_name: 视频名称（用于牌组名）
        cards: 卡片数据列表
        output_dir: 输出目录
        audio_dir: 音频目录
        screenshot_dir: 截图目录
        card_styles: 卡片样式列表，如 ["sentence"]、["vocab"]、["sentence", "vocab"]
        theme: 主题名称，可选 "default"、"minimal"、"netflix"、"dictionary"
        theme_overrides: CSS 变量覆盖字典

    Returns:
        输出的 .apkg 文件路径
    """
    if card_styles is None:
        card_styles = ["sentence"]

    deck_name = Path(video_name).stem

    card_data_list = []
    for i, c in enumerate(cards):
        print(f"卡片 {i}: audio_path={c.get('audio_path', 'N/A')}, screenshot_path={c.get('screenshot_path', 'N/A')}")
        card_data_list.append(CardData(
            index=c.get("index", i),
            sentence=c.get("text", ""),
            translation=c.get("translation", ""),
            notes=c.get("notes", ""),
            audio_path=c.get("audio_path", ""),
            screenshot_path=c.get("screenshot_path", ""),
            word=c.get("word", ""),
            definition=c.get("definition", "")
        ))

    deck = create_deck(deck_name, card_data_list, card_styles=card_styles, theme=theme, theme_overrides=theme_overrides)

    # 收集媒体文件
    audio_files = []
    screenshot_files = []

    for c in card_data_list:
        if c.audio_path and Path(c.audio_path).exists():
            audio_files.append(c.audio_path)
            print(f"音频文件存在: {c.audio_path}")
        else:
            print(f"音频文件不存在: {c.audio_path}")

        if c.screenshot_path and Path(c.screenshot_path).exists():
            screenshot_files.append(c.screenshot_path)
            print(f"截图文件存在: {c.screenshot_path}")
        else:
            print(f"截图文件不存在: {c.screenshot_path}")

    print(f"有效音频文件总数: {len(audio_files)}")
    print(f"有效截图文件总数: {len(screenshot_files)}")

    # 保存
    output_path = Path(output_dir) / f"{deck_name}.apkg"
    save_deck_with_media(
        deck,
        str(output_path),
        audio_files=audio_files,
        screenshot_files=screenshot_files,
        audio_dir=audio_dir,
        screenshot_dir=screenshot_dir
    )

    # 验证文件是否创建成功
    if output_path.exists():
        print(f"牌组已生成: {output_path}")
        print(f"文件大小: {output_path.stat().st_size} bytes")
        return str(output_path)
    else:
        raise ClipLingoError(ErrorCode.INTERNAL_ERROR, f"牌组生成失败: {output_path} 不存在")


if __name__ == '__main__':
    # 测试
    deck = create_deck("测试牌组", [])
    print(f"测试牌组创建成功，ID: {deck.deck_id}")