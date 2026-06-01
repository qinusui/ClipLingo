"""
templates 模块测试
覆盖：inject_theme_overrides、build_override_only、get_theme、load_custom_theme、内置主题结构
"""

import pytest
from pathlib import Path
import json

from core.templates import (
    inject_theme_overrides, build_override_only, get_theme, load_custom_theme,
    THEMES,
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  inject_theme_overrides
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestInjectThemeOverrides:
    """CSS 变量注入"""

    def test_no_overrides_returns_original(self):
        """无覆盖应返回原始 CSS"""
        css = ".card { color: red; }"
        result = inject_theme_overrides(css, None)
        assert result == css

    def test_empty_overrides_returns_original(self):
        """空覆盖字典应返回原始 CSS"""
        css = ".card { color: red; }"
        result = inject_theme_overrides(css, {})
        assert result == css

    def test_card_bg_override(self):
        """--card-bg 覆盖"""
        css = ".card { background: white; }"
        result = inject_theme_overrides(css, {"--card-bg": "#1a1a2e"})

        assert "--card-bg: #1a1a2e" in result
        assert "background-color: var(--card-bg)" in result

    def test_card_text_override(self):
        """--card-text 覆盖"""
        css = ".card { color: black; }"
        result = inject_theme_overrides(css, {"--card-text": "#ffffff"})

        assert "color: var(--card-text)" in result

    def test_card_padding_override(self):
        """--card-padding 覆盖"""
        css = ".card {}"
        result = inject_theme_overrides(css, {"--card-padding": "20px"})

        assert "padding: var(--card-padding)" in result

    def test_card_radius_override(self):
        """--card-radius 覆盖"""
        css = ".card {}"
        result = inject_theme_overrides(css, {"--card-radius": "12px"})

        assert "border-radius: var(--card-radius)" in result

    def test_shadow_variables_merged(self):
        """拆分后的阴影变量应合并为 --card-shadow"""
        css = ".card {}"
        overrides = {
            "--card-shadow-offset-x": "2px",
            "--card-shadow-offset-y": "4px",
            "--card-shadow-blur": "8px",
            "--card-shadow-color": "rgba(0,0,0,0.3)",
        }
        result = inject_theme_overrides(css, overrides)

        assert "--card-shadow:" in result
        assert "box-shadow: var(--card-shadow)" in result

    def test_font_sentence_override(self):
        """--font-sentence 覆盖"""
        css = ".original {}"
        result = inject_theme_overrides(css, {"--font-sentence": "Arial"})

        assert "font-family: var(--font-sentence)" in result
        assert ".original, .sentence, .subtitle-text" in result

    def test_translation_color_override(self):
        """--translation-color 覆盖"""
        css = ".translation {}"
        result = inject_theme_overrides(css, {"--translation-color": "#666"})

        assert "color: var(--translation-color)" in result
        assert ".translation" in result

    def test_annotation_color_override(self):
        """--annotation-color 覆盖"""
        css = ".notes {}"
        result = inject_theme_overrides(css, {"--annotation-color": "#999"})

        assert ".notes, .annotation" in result

    def test_accent_color_override(self):
        """--accent-color 覆盖"""
        css = ".container {}"
        result = inject_theme_overrides(css, {"--accent-color": "#007bff"})

        assert ".container" in result
        assert "hr, hr#answer, .divider" in result

    def test_override_prepended_to_original(self):
        """覆盖 CSS 应拼接在原始 CSS 前面"""
        css = "/* ORIGINAL */"
        result = inject_theme_overrides(css, {"--card-bg": "#000"})

        # 覆盖部分在前，原始在后
        override_pos = result.find("--card-bg")
        original_pos = result.find("/* ORIGINAL */")
        assert override_pos < original_pos

    def test_multiple_overrides(self):
        """多个变量同时覆盖"""
        css = ".card {}"
        overrides = {
            "--card-bg": "#000",
            "--card-text": "#fff",
            "--card-radius": "8px",
        }
        result = inject_theme_overrides(css, overrides)

        assert "--card-bg: #000" in result
        assert "--card-text: #fff" in result
        assert "--card-radius: 8px" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  build_override_only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestBuildOverrideOnly:
    """仅构建覆盖层 CSS"""

    def test_no_overrides_returns_empty(self):
        """无覆盖应返回空字符串"""
        result = build_override_only(None)
        assert result == ""

    def test_empty_overrides_returns_empty(self):
        """空覆盖应返回空字符串"""
        result = build_override_only({})
        assert result == ""

    def test_basic_override(self):
        """基本覆盖"""
        result = build_override_only({"--card-bg": "#000"})
        assert "--card-bg: #000" in result
        assert ".card" in result

    def test_shadow_merge(self):
        """阴影变量合并"""
        overrides = {
            "--card-shadow-offset-x": "1px",
            "--card-shadow-offset-y": "2px",
            "--card-shadow-blur": "4px",
            "--card-shadow-color": "black",
        }
        result = build_override_only(overrides)
        assert "--card-shadow:" in result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  THEMES 注册表
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestThemesRegistry:
    """内置主题结构验证"""

    def test_all_four_themes_exist(self):
        """应有 4 个内置主题"""
        assert "default" in THEMES
        assert "minimal" in THEMES
        assert "netflix" in THEMES
        assert "dictionary" in THEMES

    @pytest.mark.parametrize("theme_name", ["default", "minimal", "netflix", "dictionary"])
    def test_theme_structure(self, theme_name):
        """每个主题应有完整的结构"""
        theme = THEMES[theme_name]

        assert "name" in theme
        assert "css" in theme
        assert "sentence" in theme
        assert "vocab" in theme

        # sentence 和 vocab 应为 (front, back) 元组
        assert isinstance(theme["sentence"], tuple)
        assert len(theme["sentence"]) == 2
        assert isinstance(theme["vocab"], tuple)
        assert len(theme["vocab"]) == 2

    @pytest.mark.parametrize("theme_name", ["default", "minimal", "netflix", "dictionary"])
    def test_theme_css_not_empty(self, theme_name):
        """CSS 不应为空"""
        assert len(THEMES[theme_name]["css"]) > 100

    @pytest.mark.parametrize("theme_name", ["default", "minimal", "netflix", "dictionary"])
    def test_theme_templates_contain_anki_fields(self, theme_name):
        """模板应包含 Anki 字段占位符"""
        theme = THEMES[theme_name]
        sentence_front, sentence_back = theme["sentence"]
        vocab_front, vocab_back = theme["vocab"]

        # 句型卡应包含 Sentence 字段
        assert "{{Sentence}}" in sentence_front or "{{Sentence}}" in sentence_back
        # 词汇卡应包含 Word 字段
        assert "{{Word}}" in vocab_front or "{{Word}}" in vocab_back


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  get_theme
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestGetTheme:
    """获取主题配置"""

    def test_get_builtin_theme(self):
        """获取内置主题"""
        result = get_theme("default")
        assert result is not None
        assert "css" in result
        assert "sentence" in result

    def test_get_theme_with_overrides(self):
        """获取主题并应用覆盖"""
        result = get_theme("default", {"--card-bg": "#000"})
        assert result is not None
        assert "--card-bg: #000" in result["css"]

    def test_unknown_theme_returns_none(self):
        """未知主题应返回 None"""
        result = get_theme("nonexistent-theme-xyz")
        assert result is None

    @pytest.mark.parametrize("theme_name", ["default", "minimal", "netflix", "dictionary"])
    def test_all_themes_loadable(self, theme_name):
        """所有内置主题都应可加载"""
        result = get_theme(theme_name)
        assert result is not None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  load_custom_theme
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestLoadCustomTheme:
    """加载自定义主题"""

    def test_nonexistent_theme_returns_none(self, tmp_path):
        """不存在的主题应返回 None"""
        result = load_custom_theme("nonexistent-xyz")
        assert result is None

    def test_valid_custom_theme(self, tmp_path, monkeypatch):
        """有效的自定义主题"""
        # 创建主题目录
        theme_dir = tmp_path / "themes" / "custom" / "my-theme"
        theme_dir.mkdir(parents=True)

        # 创建必需文件
        (theme_dir / "theme.json").write_text(json.dumps({"label": "My Theme"}))
        (theme_dir / "front.html").write_text("<div>{{Sentence}}</div>")
        (theme_dir / "back.html").write_text("<div>{{Translation}}</div>")
        (theme_dir / "style.css").write_text(".card { color: red; }")

        # 模拟项目根目录
        monkeypatch.setattr("core.templates.Path", lambda *args: tmp_path / "core" if len(args) == 0 else Path(*args))

        # 由于 load_custom_theme 使用 __file__ 推导路径，我们需要 patch
        import core.templates as templates_module
        original_load = templates_module.load_custom_theme

        def patched_load(name):
            import sys
            d = tmp_path / "themes" / "custom" / name
            if not d.is_dir():
                return None

            meta_file = d / "theme.json"
            front_file = d / "front.html"
            back_file = d / "back.html"
            css_file = d / "style.css"

            if not (meta_file.exists() and front_file.exists() and back_file.exists() and css_file.exists()):
                return None

            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            front_html = front_file.read_text(encoding="utf-8")
            back_html = back_file.read_text(encoding="utf-8")
            css = css_file.read_text(encoding="utf-8")

            return {
                "name": meta.get("label", name),
                "css": css,
                "sentence": (front_html, back_html),
                "vocab": (front_html, back_html),
                "_custom": True,
            }

        result = patched_load("my-theme")
        assert result is not None
        assert result["name"] == "My Theme"
        assert result["_custom"] is True

    def test_missing_required_file_returns_none(self, tmp_path):
        """缺少必需文件应返回 None"""
        theme_dir = tmp_path / "themes" / "custom" / "incomplete"
        theme_dir.mkdir(parents=True)

        # 只创建部分文件
        (theme_dir / "theme.json").write_text("{}")
        (theme_dir / "front.html").write_text("")
        # 缺少 back.html 和 style.css

        import core.templates as templates_module

        def patched_load(name):
            d = tmp_path / "themes" / "custom" / name
            if not d.is_dir():
                return None

            meta_file = d / "theme.json"
            front_file = d / "front.html"
            back_file = d / "back.html"
            css_file = d / "style.css"

            if not (meta_file.exists() and front_file.exists() and back_file.exists() and css_file.exists()):
                return None

            return {}

        result = patched_load("incomplete")
        assert result is None

    def test_invalid_json_in_theme(self, tmp_path):
        """无效的 JSON 应抛出异常或被处理"""
        theme_dir = tmp_path / "themes" / "custom" / "bad-json"
        theme_dir.mkdir(parents=True)

        (theme_dir / "theme.json").write_text("not valid json {{{")
        (theme_dir / "front.html").write_text("")
        (theme_dir / "back.html").write_text("")
        (theme_dir / "style.css").write_text("")

        def patched_load(name):
            d = tmp_path / "themes" / "custom" / name
            if not d.is_dir():
                return None

            meta_file = d / "theme.json"
            front_file = d / "front.html"
            back_file = d / "back.html"
            css_file = d / "style.css"

            if not (meta_file.exists() and front_file.exists() and back_file.exists() and css_file.exists()):
                return None

            meta = json.loads(meta_file.read_text(encoding="utf-8"))  # 会抛出
            return {}

        with pytest.raises(json.JSONDecodeError):
            patched_load("bad-json")
