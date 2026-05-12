"""
主题管理 API

- GET  /api/themes                    列出所有主题（内置 + 自定义）
- GET  /api/themes/{theme}            加载 CSS 变量覆盖
- POST /api/themes/{theme}            保存 CSS 变量覆盖
- POST /api/themes/import             导入自定义主题 ZIP 包
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
    "style", "link", "meta", "section", "header", "footer", "main", "nav",
    "article", "aside", "figure", "figcaption", "blockquote", "pre", "code",
    "small", "sub", "sup", "mark", "del", "ins", "dl", "dt", "dd",
}


class ThemeOverridesPayload(BaseModel):
    variables: dict  # { "--card-bg": "#1a1a2e", ... }


def _theme_file(theme: str) -> Path:
    return THEMES_DIR / f"{theme}.json"


def _map_template_vars(html: str) -> str:
    """将用户友好的 {{sentence}} 映射为 Anki 标准 {{Sentence}}，包括条件变体"""
    for user_var, anki_var in VAR_MAP.items():
        # 直接替换：{{sentence}} → {{Sentence}}
        html = html.replace(user_var, anki_var)
        # 条件开始：{{#sentence}} → {{#Sentence}}
        html = html.replace(user_var.replace("{{", "{{#"), anki_var.replace("{{", "{{#"))
        # 条件结束：{{/sentence}} → {{/Sentence}}
        html = html.replace(user_var.replace("{{", "{{/"), anki_var.replace("{{", "{{/"))
        # 反向条件：{{^sentence}} → {{^Sentence}}
        html = html.replace(user_var.replace("{{", "{{^"), anki_var.replace("{{", "{{^"))
    return html


def _sanitize_html(html: str) -> str:
    """移除不允许的标签和危险属性（保留标签名和 class/style）"""
    # 移除 <script> <iframe> <object> <embed> 等危险标签
    dangerous = r"</?(script|iframe|object|embed|form|input|button|select|textarea|link|meta|base|applet)\b[^>]*/?>"
    html = re.sub(dangerous, "", html, flags=re.IGNORECASE | re.DOTALL)

    # 移除 on* 事件属性
    html = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*'[^']*'", "", html, flags=re.IGNORECASE)

    # 移除 javascript: 协议
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


# ─────────────────────────── 路由 ───────────────────────────


@router.get("")
async def list_themes():
    """列出所有可用主题（内置 + 自定义）"""
    themes = [
        {"name": "default", "label": "经典", "isBuiltin": True},
        {"name": "minimal", "label": "极简沉浸", "isBuiltin": True},
        {"name": "netflix", "label": "Netflix 剧照", "isBuiltin": True},
        {"name": "dictionary", "label": "硬核词典", "isBuiltin": True},
    ]

    # 扫描自定义主题
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
                    })

    return {"themes": themes}


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
    }


@router.get("/{theme}")
async def load_overrides(theme: str):
    """加载指定主题的 CSS 变量覆盖"""
    if theme not in VALID_THEMES:
        # 检查是否是已安装的自定义主题
        meta = _read_custom_theme_meta(theme)
        if meta:
            return {"theme": theme, "variables": {}, "isCustom": True}
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")
    f = _theme_file(theme)
    if f.exists():
        return {"theme": theme, "variables": json.loads(f.read_text(encoding="utf-8"))}
    return {"theme": theme, "variables": {}}


@router.post("/import")
async def import_theme_zip(file: UploadFile = File(...)):
    """导入自定义主题 ZIP 包

    ZIP 必须包含：
    - theme.json: { "name": "my-theme", "label": "My Theme", "version": 1, "author": "..." }
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

            # 检查必要文件（支持根目录和一级子目录）
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

            # 读取 theme.json
            meta = json.loads(zf.read(found["theme.json"]))
            theme_name = (meta.get("name") or "").strip()
            if not theme_name:
                raise HTTPException(status_code=400, detail="theme.json 缺少 name 字段")

            # 验证主题名
            if not re.match(r"^[a-zA-Z0-9_-]+$", theme_name):
                raise HTTPException(
                    status_code=400, detail="主题名只能包含字母、数字、连字符和下划线"
                )
            if theme_name in VALID_THEMES:
                raise HTTPException(
                    status_code=400,
                    detail=f"'{theme_name}' 是内置主题名，请更换",
                )

            # 读取并处理模板文件
            front_html = zf.read(found["front.html"]).decode("utf-8")
            back_html = zf.read(found["back.html"]).decode("utf-8")
            style_css = zf.read(found["style.css"]).decode("utf-8")

            # 映射模板变量
            front_html = _map_template_vars(front_html)
            back_html = _map_template_vars(back_html)

            # 安全过滤
            front_html = _sanitize_html(front_html)
            back_html = _sanitize_html(back_html)

            # 写入自定义主题目录
            theme_dir = CUSTOM_THEMES_DIR / theme_name
            if theme_dir.exists():
                import shutil
                shutil.rmtree(theme_dir)
            theme_dir.mkdir(parents=True, exist_ok=True)

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
    if theme not in VALID_THEMES:
        meta = _read_custom_theme_meta(theme)
        if not meta:
            raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")
        # 自定义主题目前不支持 CSS 变量覆盖
        raise HTTPException(status_code=400, detail="自定义主题暂不支持 CSS 变量编辑")
    f = _theme_file(theme)
    f.write_text(json.dumps(payload.variables, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"theme": theme, "variables": payload.variables, "saved": True}


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
    if theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"无效的主题名：{theme}")
    f = _theme_file(theme)
    if f.exists():
        f.unlink()
    return {"theme": theme, "reset": True}
