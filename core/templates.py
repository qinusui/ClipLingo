"""
模板模块 - 卡片 HTML/CSS 模板定义（Anki 模板的单一真相来源）

所有内置主题的 HTML 模板、CSS 样式和变量覆盖逻辑集中在此。
pack_apkg.py、syncToAnki.ts 和 CardPreview 都从此处获取模板。
"""

import json
import os
from pathlib import Path


def inject_theme_overrides(css: str, overrides: dict | None) -> str:
    """将用户 CSS 变量注入到主题 CSS 前面

    只对实际被修改的 CSS 变量生成选择器规则，未涉及的属性保持主题默认值。
    避免 `var(--card-bg, inherit)` 在主题使用硬编码值时回退到透明，导致背景异常。
    """
    if not overrides:
        return css

    ov = dict(overrides)

    # 合并拆分后的阴影变量为 --card-shadow
    shadow_keys = {"--card-shadow-offset-x", "--card-shadow-offset-y", "--card-shadow-blur", "--card-shadow-color"}
    if shadow_keys & set(ov.keys()):
        ox = ov.pop("--card-shadow-offset-x", "0px")
        oy = ov.pop("--card-shadow-offset-y", "2px")
        blur = ov.pop("--card-shadow-blur", "0px")
        color = ov.pop("--card-shadow-color", "rgba(0,0,0,0.15)")
        ov["--card-shadow"] = f"{ox} {oy} {blur} 0px {color}"

    # :root 块：声明所有被覆盖的变量
    declarations = "\n".join(f"  {k}: {v};" for k, v in ov.items())
    lines = ["/* ── 用户自定义样式覆盖 ── */", ":root {", declarations, "}", ""]

    # 按需生成选择器规则：只对实际被覆盖的变量添加 !important 规则
    # ── .card ──
    card_parts = []
    if "--card-bg" in ov:
        card_parts.append("background-image: none !important; background-color: var(--card-bg) !important")
    if "--card-text" in ov:
        card_parts.append("color: var(--card-text) !important")
    if "--card-padding" in ov:
        card_parts.append("padding: var(--card-padding) !important")
    if "--card-radius" in ov:
        card_parts.append("border-radius: var(--card-radius) !important")
    if "--card-shadow" in ov:
        card_parts.append("box-shadow: var(--card-shadow) !important")
    if card_parts:
        lines.append(f'.card {{ {" ".join(card_parts)} }}')

    # ── .original / .sentence / .subtitle-text ──
    orig_parts = []
    if "--font-sentence" in ov:
        orig_parts.append("font-family: var(--font-sentence) !important")
    if "--font-size-sentence" in ov:
        orig_parts.append("font-size: var(--font-size-sentence) !important")
    if orig_parts:
        lines.append(f'.original, .sentence, .subtitle-text {{ {" ".join(orig_parts)} }}')

    # ── .translation ──
    trans_parts = []
    if "--translation-color" in ov:
        trans_parts.append("color: var(--translation-color) !important")
    if "--font-translation" in ov:
        trans_parts.append("font-family: var(--font-translation) !important")
    if "--font-size-translation" in ov:
        trans_parts.append("font-size: var(--font-size-translation) !important")
    if trans_parts:
        lines.append(f'.translation {{ {" ".join(trans_parts)} }}')

    # ── .notes / .annotation ──
    if "--annotation-color" in ov:
        lines.append(".notes, .annotation { color: var(--annotation-color) !important; }")

    # ── .container / hr ──
    if "--accent-color" in ov:
        lines.append(".container { border-color: var(--accent-color) !important; }")
        lines.append("hr, hr#answer, .divider { border-color: var(--accent-color) !important; }")

    override_css = "\n".join(lines) + "\n"
    return override_css + "\n" + css


def build_override_only(overrides: dict | None) -> str:
    """构建覆盖层 CSS，不含主题 CSS（供前端独立注入，不拼接到模板 CSS 前面）"""
    if not overrides:
        return ""

    ov = dict(overrides)

    # 合并拆分后的阴影变量为 --card-shadow
    shadow_keys = {"--card-shadow-offset-x", "--card-shadow-offset-y", "--card-shadow-blur", "--card-shadow-color"}
    if shadow_keys & set(ov.keys()):
        ox = ov.pop("--card-shadow-offset-x", "0px")
        oy = ov.pop("--card-shadow-offset-y", "2px")
        blur = ov.pop("--card-shadow-blur", "0px")
        color = ov.pop("--card-shadow-color", "rgba(0,0,0,0.15)")
        ov["--card-shadow"] = f"{ox} {oy} {blur} 0px {color}"

    declarations = "\n".join(f"  {k}: {v};" for k, v in ov.items())
    lines = ["/* ── 用户自定义样式覆盖 ── */", ":root {", declarations, "}", ""]

    # ── .card ──
    card_parts = []
    if "--card-bg" in ov:
        card_parts.append("background-image: none !important; background-color: var(--card-bg) !important")
    if "--card-text" in ov:
        card_parts.append("color: var(--card-text) !important")
    if "--card-padding" in ov:
        card_parts.append("padding: var(--card-padding) !important")
    if "--card-radius" in ov:
        card_parts.append("border-radius: var(--card-radius) !important")
    if "--card-shadow" in ov:
        card_parts.append("box-shadow: var(--card-shadow) !important")
    if card_parts:
        lines.append(f'.card {{ {" ".join(card_parts)} }}')

    orig_parts = []
    if "--font-sentence" in ov:
        orig_parts.append("font-family: var(--font-sentence) !important")
    if "--font-size-sentence" in ov:
        orig_parts.append("font-size: var(--font-size-sentence) !important")
    if orig_parts:
        lines.append(f'.original, .sentence, .subtitle-text {{ {" ".join(orig_parts)} }}')

    trans_parts = []
    if "--translation-color" in ov:
        trans_parts.append("color: var(--translation-color) !important")
    if "--font-translation" in ov:
        trans_parts.append("font-family: var(--font-translation) !important")
    if "--font-size-translation" in ov:
        trans_parts.append("font-size: var(--font-size-translation) !important")
    if trans_parts:
        lines.append(f'.translation {{ {" ".join(trans_parts)} }}')

    if "--annotation-color" in ov:
        lines.append(".notes, .annotation { color: var(--annotation-color) !important; }")

    if "--accent-color" in ov:
        lines.append(".container { border-color: var(--accent-color) !important; }")
        lines.append("hr, hr#answer, .divider { border-color: var(--accent-color) !important; }")

    return "\n".join(lines) + "\n"


# ── 统一样式 ──────────────────────────────────────────────
_CSS = """\
.card {
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 18px;
  text-align: center;
  color: #2c3e50;
  background-color: #f8f9fa;
  margin: 0;
  padding: 10px;
}
.container { max-width: 600px; margin: 0 auto; }
.image-box img {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  margin-bottom: 10px;
}
/* ── 句型卡 ── */
.original { font-weight: 600; font-size: 1.2em; color: #000; margin-top: 15px; }
.translation { color: #666; font-size: 0.95em; margin-top: 8px; }
.notes {
  text-align: left;
  background: #fff;
  border-left: 4px solid #007bff;
  padding: 10px;
  margin-top: 15px;
  font-size: 0.9em;
  border-radius: 4px;
  white-space: pre-line;
}
/* ── 词汇卡 ── */
.target-word {
  font-size: 2.5em;
  font-weight: 800;
  color: #007bff;
  margin: 40px 0 10px 0;
}
.word-meaning {
  font-size: 1.4em;
  color: #28a745;
  font-weight: 500;
  margin-bottom: 20px;
}
.hint {
  color: #999;
  font-size: 0.85em;
  margin-top: 20px;
}
.example-box {
  background: #f0f2f5;
  padding: 15px;
  border-radius: 12px;
  text-align: left;
  margin-top: 15px;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.7em;
  padding: 2px 8px;
  background: #6c757d;
  color: white;
  border-radius: 4px;
  margin-bottom: 8px;
}
.example-box .image-box img {
  width: 100%;
  height: auto;
  border-radius: 8px;
}
.example-box .original {
  font-weight: 600;
  font-size: 1em;
  color: #333;
  margin: 8px 0;
}
/* ── 夜间模式 ── */
.nightMode .card { background-color: #1e1e1e; color: #eee; }
.nightMode .translation { color: #aaa; }
.nightMode .notes { background: #2d2d2d; border-left-color: #375a7f; }
.nightMode .target-word { color: #4da6ff; }
.nightMode .word-meaning { color: #5cb85c; }
.nightMode .hint { color: #666; }
.nightMode .example-box { background: #2d2d2d; }
.nightMode .example-box .original { color: #ccc; }"""

# ── 句型卡模板 ──────────────────────────────────────────
_SENTENCE_FRONT = """\
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
  {{^Screenshot}}
  <div class="original">{{Sentence}}</div>
  {{/Screenshot}}
</div>"""

_SENTENCE_BACK = """\
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <hr id="answer">
  <div class="text-content">
    <div class="original">{{Sentence}}</div>
    {{#Translation}}
    <div class="translation">{{Translation}}</div>
    {{/Translation}}
    {{#Notes}}
    <div class="notes">{{Notes}}</div>
    {{/Notes}}
  </div>
</div>"""

# ── 词汇卡模板 ──────────────────────────────────────────
_VOCAB_FRONT = """\
<div class="container">
  {{#Word}}
  <div class="target-word">{{Word}}</div>
  <div class="hint">试着回想这个词在视频里的意思</div>
  {{/Word}}
  {{^Word}}
  <div class="original">{{Sentence}}</div>
  {{/Word}}
</div>"""

_VOCAB_BACK = """\
<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}

  <hr id="answer">

  <div class="example-box">
    <div class="tag">CONTEXT / 例句</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主题 1: 极简沉浸风 (Minimal Immersive)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CSS_MINIMAL = """\
.card {
  font-family: Georgia, "Noto Serif SC", "Source Han Serif CN", serif;
  font-size: 20px;
  text-align: center;
  color: #1a1a2e;
  background-color: #fafaf8;
  margin: 0;
  padding: 0;
  position: relative;
  min-height: 80vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bg-image {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  opacity: 0.12;
  background-size: cover;
  background-position: center;
  pointer-events: none;
}
.container {
  position: relative;
  max-width: 560px;
  margin: 0 auto;
  padding: 40px 30px;
}
.image-box { display: none; }
.divider {
  width: 40px;
  height: 1px;
  background: #c0b8a8;
  margin: 24px auto;
}
.original {
  font-weight: 600;
  font-size: 1.3em;
  line-height: 1.6;
  color: #1a1a2e;
  letter-spacing: 0.01em;
}
.translation {
  color: #8a8578;
  font-size: 0.95em;
  margin-top: 12px;
  line-height: 1.5;
}
.notes {
  text-align: left;
  color: #6b6560;
  font-size: 0.85em;
  margin-top: 20px;
  padding: 12px 0;
  border-top: 1px solid #e8e4dc;
  white-space: pre-line;
  font-family: "Courier New", "Source Code Pro", monospace;
  line-height: 1.6;
}
.target-word {
  font-size: 3em;
  font-weight: 700;
  color: #1a1a2e;
  margin: 0 0 8px 0;
  letter-spacing: -0.02em;
}
.phonetic {
  font-size: 0.9em;
  color: #a09888;
  font-style: italic;
  margin-bottom: 16px;
}
.word-meaning {
  font-size: 1.3em;
  color: #8a8578;
  font-weight: 400;
  margin: 16px 0;
}
.hint {
  color: #c0b8a8;
  font-size: 0.8em;
  margin-top: 24px;
  letter-spacing: 0.05em;
}
.example-box {
  text-align: left;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #e8e4dc;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.65em;
  padding: 2px 8px;
  color: #a09888;
  border: 1px solid #e0dcd4;
  border-radius: 2px;
  margin-bottom: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.example-box .image-box { display: none; }
.example-box .original {
  font-weight: 400;
  font-size: 0.95em;
  color: #3a3530;
  margin: 6px 0;
  line-height: 1.5;
}
.nightMode .card { background-color: #161618; color: #d8d4cc; }
.nightMode .bg-image { opacity: 0.08; }
.nightMode .original { color: #d8d4cc; }
.nightMode .translation { color: #7a7568; }
.nightMode .notes { color: #8a8578; border-top-color: #2a2824; }
.nightMode .target-word { color: #d8d4cc; }
.nightMode .word-meaning { color: #7a7568; }
.nightMode .hint { color: #4a4540; }
.nightMode .divider { background: #3a3830; }
.nightMode .example-box { border-top-color: #2a2824; }
.nightMode .example-box .tag { color: #7a7568; border-color: #3a3830; }
.nightMode .example-box .original { color: #a09888; }"""

_MINIMAL_SENTENCE_FRONT = """\
<div class="bg-image" style="background-image: url({{Screenshot}})"></div>
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
  {{^Screenshot}}
  <div class="original">{{Sentence}}</div>
  {{/Screenshot}}
</div>"""

_MINIMAL_SENTENCE_BACK = """\
<div class="bg-image" style="background-image: url({{Screenshot}})"></div>
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="original">{{Sentence}}</div>
  <div class="divider"></div>
  {{#Translation}}
  <div class="translation">{{Translation}}</div>
  {{/Translation}}
  {{#Notes}}
  <div class="notes">{{Notes}}</div>
  {{/Notes}}
</div>"""

_MINIMAL_VOCAB_FRONT = """\
<div class="container">
  {{#Word}}
  <div class="target-word">{{Word}}</div>
  <div class="hint">recall the meaning from context</div>
  {{/Word}}
  {{^Word}}
  <div class="original">{{Sentence}}</div>
  {{/Word}}
</div>"""

_MINIMAL_VOCAB_BACK = """\
<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}
  <div class="divider"></div>
  <div class="example-box">
    <div class="tag">Context</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
</div>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主题 2: Netflix 剧照风 (Netflix Stills)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CSS_NETFLIX = """\
.card {
  font-family: "Helvetica Neue", Arial, "PingFang SC", sans-serif;
  font-size: 18px;
  text-align: center;
  color: #e5e5e5;
  background-color: #141414;
  margin: 0;
  padding: 0;
}
.container { max-width: 600px; margin: 0 auto; padding: 16px; }
.image-box img {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.6);
}
.audio-box { margin-top: 8px; }
.original {
  font-weight: 600;
  font-size: 1.15em;
  color: #ffffff;
  margin-top: 14px;
  line-height: 1.5;
}
.translation {
  color: #e50914;
  font-size: 0.95em;
  margin-top: 8px;
  font-weight: 500;
}
.notes {
  text-align: left;
  background: rgba(255,255,255,0.08);
  border-left: 3px solid #e50914;
  padding: 10px 12px;
  margin-top: 14px;
  font-size: 0.85em;
  border-radius: 0 4px 4px 0;
  white-space: pre-line;
  color: #b3b3b3;
}
.progress-bar {
  width: 100%;
  height: 3px;
  background: #333;
  margin-top: 20px;
  border-radius: 2px;
  overflow: hidden;
}
.progress-bar::after {
  content: '';
  display: block;
  width: 35%;
  height: 100%;
  background: #e50914;
  border-radius: 2px;
}
.target-word {
  font-size: 2.8em;
  font-weight: 800;
  color: #ffffff;
  margin: 30px 0 8px 0;
  text-shadow: 0 2px 20px rgba(229,9,20,0.3);
}
.word-meaning {
  font-size: 1.3em;
  color: #e50914;
  font-weight: 600;
  margin-bottom: 16px;
}
.hint {
  color: #666;
  font-size: 0.85em;
  margin-top: 16px;
}
.example-box {
  background: rgba(255,255,255,0.06);
  padding: 14px;
  border-radius: 8px;
  text-align: left;
  margin-top: 14px;
  border: 1px solid rgba(255,255,255,0.08);
}
.example-box .tag {
  display: inline-block;
  font-size: 0.65em;
  padding: 2px 10px;
  background: #e50914;
  color: white;
  border-radius: 3px;
  margin-bottom: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.example-box .image-box img {
  width: 100%;
  border-radius: 4px;
}
.example-box .original {
  font-weight: 600;
  font-size: 0.95em;
  color: #e5e5e5;
  margin: 8px 0;
}
.nightMode .card { background-color: #141414; }
.nightMode .original { color: #fff; }
.nightMode .translation { color: #e50914; }
.nightMode .notes { background: rgba(255,255,255,0.08); border-left-color: #e50914; color: #b3b3b3; }
.nightMode .target-word { color: #fff; }
.nightMode .word-meaning { color: #e50914; }
.nightMode .hint { color: #555; }
.nightMode .example-box { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.08); }
.nightMode .example-box .original { color: #e5e5e5; }"""

_NETFLIX_SENTENCE_FRONT = """\
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
  {{^Screenshot}}
  <div class="original">{{Sentence}}</div>
  {{/Screenshot}}
</div>"""

_NETFLIX_SENTENCE_BACK = """\
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="original">{{Sentence}}</div>
  {{#Translation}}
  <div class="translation">{{Translation}}</div>
  {{/Translation}}
  {{#Notes}}
  <div class="notes">{{Notes}}</div>
  {{/Notes}}
  <div class="progress-bar"></div>
</div>"""

_NETFLIX_VOCAB_FRONT = """\
<div class="container">
  {{#Word}}
  <div class="target-word">{{Word}}</div>
  <div class="hint">recall from the scene</div>
  {{/Word}}
  {{^Word}}
  <div class="original">{{Sentence}}</div>
  {{/Word}}
</div>"""

_NETFLIX_VOCAB_BACK = """\
<div class="container">
  <div class="target-word">{{Word}}</div>
  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}
  <div class="example-box">
    <div class="tag">SCENE</div>
    {{#Screenshot}}
    <div class="image-box">{{Screenshot}}</div>
    {{/Screenshot}}
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>
  <div class="progress-bar"></div>
</div>"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主题 3: 硬核词典风 (Hardcore Dictionary)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_CSS_DICTIONARY = """\
.card {
  font-family: "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
  font-size: 17px;
  text-align: left;
  color: #2d2a26;
  background-color: #fefcf3;
  margin: 0;
  padding: 0;
  line-height: 1.55;
}
.container {
  max-width: 580px;
  margin: 0 auto;
  padding: 24px 28px;
  border: 1px solid #e0dcd0;
  box-shadow: 2px 2px 8px rgba(0,0,0,0.06);
}
.image-box { display: none; }
.section-label {
  font-size: 0.7em;
  font-weight: 700;
  color: #8b7355;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  margin: 16px 0 6px 0;
  padding-bottom: 4px;
  border-bottom: 1px solid #e8e2d4;
}
.section-label:first-child { margin-top: 0; }
.original {
  font-weight: 600;
  font-size: 1.1em;
  color: #2d2a26;
  line-height: 1.6;
}
.translation {
  color: #5a5248;
  font-size: 0.95em;
  margin-top: 4px;
}
.notes {
  background: #f5f0e4;
  border-left: 3px solid #c4a96a;
  padding: 10px 12px;
  margin-top: 6px;
  font-size: 0.85em;
  border-radius: 0 3px 3px 0;
  white-space: pre-line;
  font-family: "Courier New", "Source Code Pro", monospace;
  color: #4a4538;
  line-height: 1.6;
}
.thumb {
  float: right;
  width: 110px;
  margin: 0 0 8px 14px;
  border: 1px solid #d4cfc0;
  border-radius: 3px;
}
.thumb .image-box { display: block; }
.thumb img {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 2px;
}
.headword {
  font-size: 2.2em;
  font-weight: 700;
  color: #2d2a26;
  margin: 0;
  display: inline;
}
.headword-phonetic {
  font-size: 0.85em;
  color: #8b7355;
  font-style: italic;
  margin-left: 8px;
}
.pos-tag {
  display: inline-block;
  font-size: 0.7em;
  font-weight: 700;
  padding: 1px 8px;
  background: #c4a96a;
  color: #fff;
  border-radius: 3px;
  margin-left: 8px;
  vertical-align: middle;
}
.word-meaning {
  font-size: 1.2em;
  color: #4a4538;
  font-weight: 600;
  margin: 10px 0;
}
.hint {
  color: #b0a890;
  font-size: 0.8em;
  margin-top: 12px;
  font-style: italic;
}
.example-box {
  background: #f5f0e4;
  padding: 12px 14px;
  border-radius: 4px;
  margin-top: 10px;
  border: 1px solid #e8e2d4;
}
.example-box .tag {
  display: inline-block;
  font-size: 0.6em;
  font-weight: 700;
  padding: 1px 6px;
  background: #8b7355;
  color: white;
  border-radius: 2px;
  margin-bottom: 6px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.example-box .image-box { display: none; }
.example-box .original {
  font-weight: 600;
  font-size: 0.95em;
  color: #3a3530;
  margin: 4px 0;
}
.dict-divider {
  border: none;
  border-top: 2px solid #c4a96a;
  margin: 16px 0 12px 0;
}
.clearfix::after { content: ''; display: table; clear: both; }
.nightMode .card { background-color: #1e1c18; color: #d4cfc0; border-color: #3a3530; }
.nightMode .container { border-color: #3a3530; box-shadow: 2px 2px 8px rgba(0,0,0,0.3); }
.nightMode .section-label { color: #a09070; border-bottom-color: #3a3530; }
.nightMode .original { color: #d4cfc0; }
.nightMode .translation { color: #a09888; }
.nightMode .notes { background: #2a2620; border-left-color: #a09070; color: #b0a890; }
.nightMode .headword { color: #e8e2d4; }
.nightMode .headword-phonetic { color: #a09070; }
.nightMode .pos-tag { background: #8b7355; }
.nightMode .word-meaning { color: #c4b898; }
.nightMode .hint { color: #6a6050; }
.nightMode .example-box { background: #2a2620; border-color: #3a3530; }
.nightMode .example-box .tag { background: #6a6050; }
.nightMode .example-box .original { color: #b0a890; }
.nightMode .dict-divider { border-top-color: #5a5040; }
.nightMode .thumb { border-color: #3a3530; }"""

_DICT_SENTENCE_FRONT = """\
<div class="container">
  <div class="image-box">{{Screenshot}}</div>
  <div class="audio-box">{{Audio}}</div>
  <div class="section-label">Sentence</div>
  {{#Screenshot}}
  <div class="original" style="text-align: center;">聆听音频，回忆句子</div>
  {{/Screenshot}}
  {{^Screenshot}}
  <div class="original" style="text-align: center;">{{Sentence}}</div>
  {{/Screenshot}}
</div>"""

_DICT_SENTENCE_BACK = """\
<div class="container clearfix">
  <div class="section-label">Sentence</div>
  {{#Screenshot}}
  <div class="thumb"><div class="image-box">{{Screenshot}}</div></div>
  {{/Screenshot}}
  <div class="original">{{Sentence}}</div>

  {{#Translation}}
  <div class="section-label">Translation</div>
  <div class="translation">{{Translation}}</div>
  {{/Translation}}

  {{#Notes}}
  <div class="section-label">Notes</div>
  <div class="notes">{{Notes}}</div>
  {{/Notes}}

  <hr class="dict-divider">
  <div class="audio-box">{{Audio}}</div>
</div>"""

_DICT_VOCAB_FRONT = """\
<div class="container">
  {{#Word}}
  <div class="section-label">Entry</div>
  <div>
    <span class="headword">{{Word}}</span>
  </div>
  <div class="hint">try to recall the definition</div>
  {{/Word}}
  {{^Word}}
  <div class="original" style="text-align: center;">{{Sentence}}</div>
  {{/Word}}
</div>"""

_DICT_VOCAB_BACK = """\
<div class="container clearfix">
  <div class="section-label">Entry</div>
  {{#Screenshot}}
  <div class="thumb"><div class="image-box">{{Screenshot}}</div></div>
  {{/Screenshot}}
  <div>
    <span class="headword">{{Word}}</span>
  </div>

  {{#Definition}}
  <div class="word-meaning">{{Definition}}</div>
  {{/Definition}}

  <hr class="dict-divider">

  <div class="section-label">Example</div>
  <div class="example-box">
    <div class="tag">Usage</div>
    <div class="original">{{Sentence}}</div>
    <div class="audio-box">{{Audio}}</div>
  </div>

  {{#Translation}}
  <div class="section-label">Translation</div>
  <div class="translation">{{Translation}}</div>
  {{/Translation}}

  {{#Notes}}
  <div class="section-label">Notes</div>
  <div class="notes">{{Notes}}</div>
  {{/Notes}}
</div>"""


# ── 主题注册表 ──────────────────────────────────────────────
THEMES = {
    "default": {
        "name": "经典",
        "css": _CSS,
        "sentence": (_SENTENCE_FRONT, _SENTENCE_BACK),
        "vocab": (_VOCAB_FRONT, _VOCAB_BACK),
    },
    "minimal": {
        "name": "极简沉浸",
        "css": _CSS_MINIMAL,
        "sentence": (_MINIMAL_SENTENCE_FRONT, _MINIMAL_SENTENCE_BACK),
        "vocab": (_MINIMAL_VOCAB_FRONT, _MINIMAL_VOCAB_BACK),
    },
    "netflix": {
        "name": "Netflix 剧照",
        "css": _CSS_NETFLIX,
        "sentence": (_NETFLIX_SENTENCE_FRONT, _NETFLIX_SENTENCE_BACK),
        "vocab": (_NETFLIX_VOCAB_FRONT, _NETFLIX_VOCAB_BACK),
    },
    "dictionary": {
        "name": "硬核词典",
        "css": _CSS_DICTIONARY,
        "sentence": (_DICT_SENTENCE_FRONT, _DICT_SENTENCE_BACK),
        "vocab": (_DICT_VOCAB_FRONT, _DICT_VOCAB_BACK),
    },
}


def load_custom_theme(name: str) -> dict | None:
    """从磁盘加载自定义主题，返回与 THEMES 兼容的配置字典，不存在返回 None"""
    import sys

    if getattr(sys, 'frozen', False):
        writable = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
    else:
        # 项目根目录（core/ → 项目根目录）
        writable = Path(__file__).parent.parent

    d = writable / "themes" / "custom" / name
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
        # 自定义主题的 sentence 和 vocab 使用同一套模板
        # 用户通过 Anki 条件语法（{{#Word}} 等）自行区分卡片类型
        "sentence": (front_html, back_html),
        "vocab": (front_html, back_html),
        "_custom": True,
    }


def get_theme(theme: str, overrides: dict | None = None) -> dict | None:
    """获取主题配置（内置或自定义），注入 CSS 变量覆盖

    Args:
        theme: 主题名称，如 "default"、"minimal"、"netflix"、"dictionary"
        overrides: CSS 变量覆盖字典，如 {"--card-bg": "#1a1a2e"}

    Returns:
        主题配置字典，包含 css、sentence、vocab 等字段。未找到时返回 None。
    """
    theme_cfg = THEMES.get(theme) or load_custom_theme(theme)
    if theme_cfg is None:
        return None
    css = inject_theme_overrides(theme_cfg["css"], overrides)
    return {**theme_cfg, "css": css}
