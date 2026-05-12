"""
打包模块 - 使用 genanki 生成可导入 Anki 的 .apkg 文件
"""

import genanki
import hashlib
import os
from pathlib import Path
from dataclasses import dataclass


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


# ── CSS 变量覆盖层模板 ──────────────────────────────────────
# 用户自定义 CSS 变量注入时，生成 :root + 选择器覆盖规则
_VARIABLE_OVERRIDE_TEMPLATE = """\
/* ── 用户自定义样式覆盖 ── */
:root {{
{variable_declarations}
}}

.card {{ background-color: var(--card-bg, inherit) !important; color: var(--card-text, inherit) !important; padding: var(--card-padding, inherit) !important; border-radius: var(--card-radius, inherit) !important; box-shadow: var(--card-shadow, none) !important; }}
.original, .sentence, .subtitle-text {{ font-family: var(--font-sentence, inherit) !important; font-size: var(--font-size-sentence, inherit) !important; }}
.translation {{ color: var(--translation-color, inherit) !important; font-family: var(--font-translation, inherit) !important; font-size: var(--font-size-translation, inherit) !important; }}
.notes, .annotation {{ color: var(--annotation-color, inherit) !important; }}
.container {{ border-color: var(--accent-color, inherit) !important; }}
hr, hr#answer, .divider {{ border-color: var(--accent-color, inherit) !important; }}
"""


def _inject_theme_overrides(css: str, overrides: dict | None) -> str:
    """将用户 CSS 变量注入到主题 CSS 前面"""
    if not overrides:
        return css
    declarations = "\n".join(f"  {k}: {v};" for k, v in overrides.items())
    override_css = _VARIABLE_OVERRIDE_TEMPLATE.format(variable_declarations=declarations)
    return override_css + "\n" + css


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


def _create_model(model_id: int, name: str, templates: list[dict], css: str = None) -> genanki.Model:
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
        css=css or _CSS
    )


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


def _load_custom_theme(name: str) -> dict | None:
    """从磁盘加载自定义主题，返回与 THEMES 兼容的配置字典，不存在返回 None"""
    import sys
    import os

    if getattr(sys, 'frozen', False):
        writable = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
    else:
        # 项目根目录
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

    import json
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

    theme_cfg = THEMES.get(theme) or _load_custom_theme(theme) or THEMES["default"]
    css = _inject_theme_overrides(theme_cfg["css"], theme_overrides)

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
        raise Exception(f"牌组生成失败: {output_path} 不存在")


if __name__ == '__main__':
    # 测试
    deck = create_deck("测试牌组", [])
    print(f"测试牌组创建成功，ID: {deck.deck_id}")