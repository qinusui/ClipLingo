"""
主题管理 API

- GET  /api/themes                    列出所有主题（内置 + 自定义）
- GET  /api/themes/variables          获取 CSS 变量元数据（字段定义、默认值）
- GET  /api/themes/{theme}            加载 CSS 变量覆盖
- POST /api/themes/{theme}            保存 CSS 变量覆盖
- POST /api/themes/import             导入自定义主题 ZIP 包
- POST /api/themes/template           获取主题模板（供预览和同步使用）
- POST /api/themes/preview-css        预览 CSS（含客户端覆盖注入，供即时预览）
- DELETE /api/themes/{theme}          删除覆盖（恢复默认）
- DELETE /api/themes/custom/{name}    删除自定义主题
"""

import json
import sys
import os
import re
import zipfile
import io
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from core.templates import get_theme, inject_theme_overrides, build_override_only

router = APIRouter()

# 可写的用户数据目录
if getattr(sys, 'frozen', False):
    _WRITABLE = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
else:
    _WRITABLE = Path(__file__).parent.parent.parent

THEMES_DIR = _WRITABLE / "themes"
THEMES_DIR.mkdir(parents=True, exist_ok=True)

CUSTOM_THEMES_DIR = THEMES_DIR / "custom"
CUSTOM_THEMES_DIR.mkdir(parents=True, exist_ok=True)

# 合法的内置主题名
VALID_THEMES = {"default", "minimal", "netflix", "dictionary"}

# ── CSS 变量元数据定义（前后端类型的单一真相来源） ──

CSS_VARIABLE_FIELDS = [
    {"key": "--card-bg",              "label": "背景色",   "labelEn": "Background",            "type": "color",  "group": "colors"},
    {"key": "--card-text",            "label": "文字色",   "labelEn": "Text Color",             "type": "color",  "group": "colors"},
    {"key": "--accent-color",         "label": "强调色",   "labelEn": "Accent Color",           "type": "color",  "group": "colors"},
    {"key": "--translation-color",    "label": "翻译色",   "labelEn": "Translation Color",      "type": "color",  "group": "colors"},
    {"key": "--annotation-color",     "label": "注释色",   "labelEn": "Annotation Color",       "type": "color",  "group": "colors"},
    {"key": "--font-sentence",        "label": "原文字体", "labelEn": "Sentence Font",           "type": "font",   "group": "fonts",
     "options": [
         "system-ui, -apple-system, sans-serif",
         'Georgia, "Noto Serif", serif',
         '"Segoe UI", Roboto, sans-serif',
         '"Microsoft YaHei", "PingFang SC", sans-serif',
         'Consolas, "Courier New", monospace',
     ],
     "optionLabels": ["System UI", "Serif", "Segoe UI", "YaHei / PingFang", "Monospace"]},
    {"key": "--font-translation",     "label": "翻译字体", "labelEn": "Translation Font",       "type": "font",   "group": "fonts",
     "options": [
         "system-ui, -apple-system, sans-serif",
         'Georgia, "Noto Serif", serif',
         '"Segoe UI", Roboto, sans-serif',
         '"Microsoft YaHei", "PingFang SC", sans-serif',
         'Consolas, "Courier New", monospace',
     ],
     "optionLabels": ["System UI", "Serif", "Segoe UI", "YaHei / PingFang", "Monospace"]},
    {"key": "--font-size-sentence",   "label": "原文字号", "labelEn": "Sentence Font Size",     "type": "size",   "group": "sizes",  "min": 10, "max": 28, "step": 1},
    {"key": "--font-size-translation","label": "翻译字号", "labelEn": "Translation Font Size",  "type": "size",   "group": "sizes",  "min": 10, "max": 28, "step": 1},
    {"key": "--card-padding",         "label": "内边距",   "labelEn": "Card Padding",            "type": "slider", "group": "spacing", "min": 4,  "max": 40, "step": 2, "unit": "px"},
    {"key": "--card-radius",          "label": "圆角",     "labelEn": "Border Radius",           "type": "slider", "group": "spacing", "min": 0,  "max": 24, "step": 2, "unit": "px"},
    # 阴影拆分为 4 个独立变量
    {"key": "--card-shadow-offset-x", "label": "阴影X偏移","labelEn": "Shadow Offset X",        "type": "slider", "group": "shadow", "min": -10, "max": 10, "step": 1, "unit": "px"},
    {"key": "--card-shadow-offset-y", "label": "阴影Y偏移","labelEn": "Shadow Offset Y",        "type": "slider", "group": "shadow", "min": -10, "max": 10, "step": 1, "unit": "px"},
    {"key": "--card-shadow-blur",     "label": "阴影模糊", "labelEn": "Shadow Blur",             "type": "slider", "group": "shadow", "min": 0,   "max": 30, "step": 1, "unit": "px"},
    {"key": "--card-shadow-color",    "label": "阴影颜色", "labelEn": "Shadow Color",            "type": "color",  "group": "shadow"},
]

# 向后兼容：保留旧 key 映射（--card-shadow → 拆分为 4 个变量）
SHADOW_LEGACY_KEY = "--card-shadow"


def _split_shadow_to_variables(shadow_value: str) -> dict:
    """将旧式 box-shadow 值拆分为独立变量。使用正则匹配 rgba/rgb/hex 颜色，避免 naive 空格拆分破坏 rgba(0, 0, 0, 0.15)"""
    if not shadow_value or shadow_value == "none":
        return {
            "--card-shadow-offset-x": "0px",
            "--card-shadow-offset-y": "2px",
            "--card-shadow-blur": "0px",
            "--card-shadow-color": "rgba(0,0,0,0.15)",
        }
    # 提取颜色部分（rgba、rgb、hex 或命名色）
    color_match = re.search(r'(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}|\b[a-z]+\b)', shadow_value.strip())
    color = color_match.group(1) if color_match else "rgba(0,0,0,0.15)"
    # 去除颜色后剩余的就是数字偏移量
    without_color = re.sub(r'(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8})', '', shadow_value).strip()
    nums = [p for p in without_color.split() if re.match(r'^-?\d', p)]
    result = {}
    if len(nums) >= 1:
        result["--card-shadow-offset-x"] = nums[0]
    if len(nums) >= 2:
        result["--card-shadow-offset-y"] = nums[1]
    if len(nums) >= 3:
        result["--card-shadow-blur"] = nums[2]
    elif len(nums) >= 2:
        result["--card-shadow-blur"] = "0px"
    result["--card-shadow-color"] = color
    return result


def _join_variables_to_shadow(variables: dict) -> str:
    """将独立阴影变量合并为 box-shadow 值"""
    ox = variables.get("--card-shadow-offset-x", "0px")
    oy = variables.get("--card-shadow-offset-y", "2px")
    blur = variables.get("--card-shadow-blur", "0px")
    color = variables.get("--card-shadow-color", "rgba(0,0,0,0.15)")
    return f"{ox} {oy} {blur} 0px {color}"


def _migrate_overrides(overrides: dict) -> dict:
    """将旧式 --card-shadow 迁移为拆分的 4 个变量"""
    if not overrides:
        return {}
    result = dict(overrides)
    if SHADOW_LEGACY_KEY in result:
        legacy = result.pop(SHADOW_LEGACY_KEY)
        if legacy and legacy != "none":
            result.update(_split_shadow_to_variables(legacy))
    return result


def _compact_overrides(overrides: dict) -> dict:
    """保存前清理：移除空值和默认值，减少存储"""
    return {k: v for k, v in overrides.items() if v and v.strip()}


# 模板变量映射：用户友好的小写 → Anki 标准字段名
VAR_MAP = {
    "{{sentence}}": "{{Sentence}}",
    "{{translation}}": "{{Translation}}",
    "{{annotation}}": "{{Notes}}",
    "{{audio}}": "{{Audio}}",
    "{{screenshot}}": "{{Screenshot}}",
    "{{word}}": "{{Word}}",
    "{{definition}}": "{{Definition}}",
}

# 允许的 HTML 标签（Anki 支持子集）
_ALLOWED_HTML = {
    "div", "span", "br", "hr", "img", "audio", "b", "i", "strong", "em",
    "table", "tr", "td", "th", "thead", "tbody", "ul", "ol", "li", "p",
    "h1", "h2", "h3", "h4", "h5", "h6", "a", "video", "source", "svg",
    "path", "circle", "rect", "g", "line", "polygon", "polyline",
    "style", "section", "header", "footer", "main", "nav",
    "article", "aside", "figure", "figcaption", "blockquote", "pre", "code",
    "small", "sub", "sup", "mark", "del", "ins", "dl", "dt", "dd",
}


class ThemeOverridesPayload(BaseModel):
    variables: dict  # { "--card-bg": "#1a1a2e", ... }


class TemplateRequest(BaseModel):
    theme: str = "default"
    overrides: dict | None = None  # { "--card-bg": "#1a1a2e", ... }


class PreviewCssRequest(BaseModel):
    theme: str = "default"
    overrides: dict | None = None


def _theme_file(theme: str) -> Path:
    return THEMES_DIR / f"{theme}.json"


def _map_template_vars(html: str) -> str:
    """将用户友好的 {{sentence}} 映射为 Anki 标准 {{Sentence}}，包括条件变体"""
    for user_var, anki_var in VAR_MAP.items():
        html = html.replace(user_var, anki_var)
        html = html.replace(user_var.replace("{{", "{{#"), anki_var.replace("{{", "{{#"))
        html = html.replace(user_var.replace("{{", "{{/"), anki_var.replace("{{", "{{/"))
        html = html.replace(user_var.replace("{{", "{{^"), anki_var.replace("{{", "{{^"))
    return html


def _sanitize_html(html: str) -> str:
    """移除不允许的标签和危险属性（保留标签名和 class/style）"""
    dangerous = r"</?(script|iframe|object|embed|form|input|button|select|textarea|link|meta|base|applet)\b[^>]*/?>"
    html = re.sub(dangerous, "", html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)
    html = re.sub(r'href\s*=\s*["\']\s*javascript:', 'href="', html, flags=re.IGNORECASE)
    html = re.sub(r'src\s*=\s*["\']\s*javascript:', 'src="', html, flags=re.IGNORECASE)
    return html


def _read_custom_theme_meta(name: str) -> dict | None:
    """读取自定义主题的 theme.json，不存在返回 None"""
    meta_file = CUSTOM_THEMES_DIR / name / "theme.json"
    if not meta_file.exists():
        return None
    return json.loads(meta_file.read_text(encoding="utf-8"))


def _read_custom_theme_files(name: str) -> dict | None:
    """读取自定义主题的所有文件内容，不存在返回 None"""
    d = CUSTOM_THEMES_DIR / name
    if not d.is_dir():
        return None
    meta_file = d / "theme.json"
    front_file = d / "front.html"
    back_file = d / "back.html"
    css_file = d / "style.css"
    if not (meta_file.exists() and front_file.exists() and back_file.exists() and css_file.exists()):
        return None
    return {
        "meta": json.loads(meta_file.read_text(encoding="utf-8")),
        "front": front_file.read_text(encoding="utf-8"),
        "back": back_file.read_text(encoding="utf-8"),
        "css": css_file.read_text(encoding="utf-8"),
    }


def _parse_theme_defaults(css: str) -> dict:
    """从主题 CSS 中提取 CSS 变量默认值"""
    defaults = {}
    for field in CSS_VARIABLE_FIELDS:
        key = field["key"]
        m = re.search(rf'{re.escape(key)}\s*:\s*([^;]+);', css)
        if m:
            defaults[key] = m.group(1).strip()
    return defaults


# ─────────────────────────── 路由 ───────────────────────────


@router.get("/variables")
async def get_variables():
    """获取 CSS 变量元数据（字段定义），供前端动态渲染编辑器"""
    return {"fields": CSS_VARIABLE_FIELDS}


@router.get("/variables/{theme}")
async def get_theme_defaults(theme: str):
    """获取指定主题的 CSS 变量默认值（从主题 CSS 解析）"""
    theme_cfg = get_theme(theme)
    if theme_cfg is None:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")
    defaults = _parse_theme_defaults(theme_cfg.get("css", ""))
    return {"theme": theme, "defaults": defaults}


@router.get("")
async def list_themes():
    """列出所有可用主题（内置 + 自定义）"""
    themes = [
        {"name": "default", "label": "经典", "isBuiltin": True},
        {"name": "minimal", "label": "极简沉浸", "isBuiltin": True},
        {"name": "netflix", "label": "Netflix 剧照", "isBuiltin": True},
        {"name": "dictionary", "label": "硬核词典", "isBuiltin": True},
    ]

    if CUSTOM_THEMES_DIR.is_dir():
        for d in sorted(CUSTOM_THEMES_DIR.iterdir()):
            if d.is_dir():
                meta = _read_custom_theme_meta(d.name)
                if meta:
                    themes.append({
                        "name": meta.get("name", d.name),
                        "label": meta.get("label", d.name),
                        "version": meta.get("version"),
                        "author": meta.get("author"),
                        "isBuiltin": False,
                        "supportsVariables": bool(meta.get("variables")),
                    })

    return {"themes": themes}


@router.post("/template")
async def get_template(req: TemplateRequest):
    """获取主题模板 HTML/CSS（供前端预览和 Anki 同步使用）

    返回内置或自定义主题的完整模板，已注入 CSS 变量覆盖。
    """
    overrides = req.overrides
    if overrides:
        overrides = _migrate_overrides(overrides)
        if any(k.startswith("--card-shadow-") for k in overrides):
            overrides[SHADOW_LEGACY_KEY] = _join_variables_to_shadow(overrides)

    theme_cfg = get_theme(req.theme, overrides)
    if theme_cfg is None:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{req.theme}")
    return {
        "name": theme_cfg["name"],
        "css": theme_cfg["css"],
        "sentence": {
            "front": theme_cfg["sentence"][0],
            "back": theme_cfg["sentence"][1],
        },
        "vocab": {
            "front": theme_cfg["vocab"][0],
            "back": theme_cfg["vocab"][1],
        },
        "isCustom": theme_cfg.get("_custom", False),
    }


@router.post("/preview-css")
async def get_preview_css(req: PreviewCssRequest):
    """获取纯覆盖层 CSS（不含主题 CSS，前端负责拼接）

    接收原始 overrides（含拆分后的阴影变量），合并为 box-shadow 后生成选择器规则。
    仅返回覆盖层，前端可将其置于更高特异性选择器下作用于 iframe。
    """
    overrides = req.overrides or {}
    overrides = dict(overrides)
    if any(k.startswith("--card-shadow-") for k in overrides):
        overrides[SHADOW_LEGACY_KEY] = _join_variables_to_shadow(overrides)
    overrides = {k: v for k, v in overrides.items() if v and not k.startswith("--card-shadow-")}

    return {"css": build_override_only(overrides)}


@router.get("/custom/{name}")
async def get_custom_theme_files(name: str):
    """获取自定义主题的模板文件（供前端预览渲染）"""
    files = _read_custom_theme_files(name)
    if not files:
        raise HTTPException(status_code=404, detail=f"自定义主题 '{name}' 不存在")
    return {
        "name": name,
        "label": files["meta"].get("label", name),
        "front": files["front"],
        "back": files["back"],
        "css": files["css"],
        "supportsVariables": bool(files["meta"].get("variables")),
    }


@router.get("/{theme}")
async def load_overrides(theme: str):
    """加载指定主题的 CSS 变量覆盖"""
    meta = _read_custom_theme_meta(theme)
    is_custom = meta is not None

    if not is_custom and theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")

    if is_custom:
        f = _theme_file(theme)
        variables = {}
        if f.exists():
            variables = json.loads(f.read_text(encoding="utf-8"))
        variables = _migrate_overrides(variables)
        return {
            "theme": theme,
            "variables": variables,
            "isCustom": True,
            "supportsVariables": bool(meta.get("variables")),
        }

    f = _theme_file(theme)
    if f.exists():
        variables = json.loads(f.read_text(encoding="utf-8"))
        variables = _migrate_overrides(variables)
        return {"theme": theme, "variables": variables}
    return {"theme": theme, "variables": {}}


@router.post("/import")
async def import_theme_zip(file: UploadFile = File(...)):
    """导入自定义主题 ZIP 包

    ZIP 必须包含：
    - theme.json: { "name": "my-theme", "label": "My Theme", "version": 1, "author": "...", "variables": [...] }
    - front.html: 正面模板（使用 {{sentence}} {{translation}} 等用户友好变量）
    - back.html:  背面模板
    - style.css:  样式表
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 文件")

    required = {"theme.json", "front.html", "back.html", "style.css"}

    try:
        contents = await file.read()
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            name_list = zf.namelist()

            found = {}
            for n in name_list:
                basename = n.split("/")[-1]
                if basename in required:
                    found[basename] = n

            missing = required - set(found.keys())
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"ZIP 缺少必要文件: {', '.join(sorted(missing))}",
                )

            meta = json.loads(zf.read(found["theme.json"]))
            theme_name = (meta.get("name") or "").strip()
            if not theme_name:
                raise HTTPException(status_code=400, detail="theme.json 缺少 name 字段")

            if not re.match(r"^[a-zA-Z0-9_-]+$", theme_name):
                raise HTTPException(
                    status_code=400, detail="主题名只能包含字母、数字、连字符和下划线"
                )
            if theme_name in VALID_THEMES:
                raise HTTPException(
                    status_code=400,
                    detail=f"'{theme_name}' 是内置主题名，请更换",
                )

            front_html = zf.read(found["front.html"]).decode("utf-8")
            back_html = zf.read(found["back.html"]).decode("utf-8")
            style_css = zf.read(found["style.css"]).decode("utf-8")

            front_html = _map_template_vars(front_html)
            back_html = _map_template_vars(back_html)

            front_html = _sanitize_html(front_html)
            back_html = _sanitize_html(back_html)

            theme_dir = CUSTOM_THEMES_DIR / theme_name
            if theme_dir.exists():
                import shutil
                shutil.rmtree(theme_dir)
            theme_dir.mkdir(parents=True, exist_ok=True)

            # 导入时自动补上 variables 声明（支持 CSS 变量编辑）
            if not meta.get("variables"):
                meta["variables"] = [f["key"] for f in CSS_VARIABLE_FIELDS]

            (theme_dir / "theme.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (theme_dir / "front.html").write_text(front_html, encoding="utf-8")
            (theme_dir / "back.html").write_text(back_html, encoding="utf-8")
            (theme_dir / "style.css").write_text(style_css, encoding="utf-8")

            return {
                "success": True,
                "name": theme_name,
                "label": meta.get("label", theme_name),
                "version": meta.get("version"),
                "author": meta.get("author"),
                "supportsVariables": bool(meta.get("variables")),
            }

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {e}")


@router.post("/{theme}")
async def save_overrides(theme: str, payload: ThemeOverridesPayload):
    """保存指定主题的 CSS 变量覆盖"""
    meta = _read_custom_theme_meta(theme)
    is_custom = meta is not None

    if not is_custom and theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")

    # 自定义主题需检查 theme.json 中是否声明了 variables 字段
    if is_custom and not meta.get("variables"):
        raise HTTPException(status_code=400, detail="该自定义主题未声明支持 CSS 变量编辑。请在 theme.json 中添加 \"variables\" 字段。")

    variables = _compact_overrides(payload.variables)
    f = _theme_file(theme)
    f.write_text(json.dumps(variables, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"theme": theme, "variables": variables, "saved": True}


@router.delete("/custom/{name}")
async def delete_custom_theme(name: str):
    """删除自定义主题"""
    if name in VALID_THEMES:
        raise HTTPException(status_code=400, detail="不能删除内置主题")
    theme_dir = CUSTOM_THEMES_DIR / name
    if not theme_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"自定义主题 '{name}' 不存在")
    import shutil
    shutil.rmtree(theme_dir)
    return {"success": True, "name": name}


@router.delete("/{theme}")
async def delete_overrides(theme: str):
    """删除指定主题的 CSS 变量覆盖（恢复默认）"""
    meta = _read_custom_theme_meta(theme)
    is_custom = meta is not None
    if not is_custom and theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")
    f = _theme_file(theme)
    if f.exists():
        f.unlink()
    return {"theme": theme, "reset": True}
