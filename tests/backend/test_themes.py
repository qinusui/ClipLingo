"""
测试主题管理 API

覆盖:
- 列出所有主题（内置 + 自定义）
- 加载/保存/删除 CSS 变量覆盖
- 导入自定义主题 ZIP 包（正常 + 异常）
- 删除自定义主题
"""

import io
import json
import zipfile
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 设置测试环境 - 在导入 app 前
import sys
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))

# 使用临时 writable 目录
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# 临时覆盖 themes 存储路径
import backend.api.themes as themes_module

TEST_THEMES_DIR = Path(tempfile.mkdtemp(prefix="cl_themes_test_"))
TEST_CUSTOM_DIR = TEST_THEMES_DIR / "custom"
TEST_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)

themes_module.THEMES_DIR = TEST_THEMES_DIR
themes_module.CUSTOM_THEMES_DIR = TEST_CUSTOM_DIR

from backend.main import app

client = TestClient(app)


def _make_test_zip(theme_name="test-theme", label="Test Theme",
                   front="<div>{{sentence}}</div>",
                   back="<div>{{translation}}</div>",
                   css=".card { color: red; }") -> bytes:
    """创建一个合法的测试主题 ZIP 包"""
    meta = {
        "name": theme_name,
        "label": label,
        "version": 1,
        "author": "Test Author",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr("theme.json", json.dumps(meta, ensure_ascii=False))
        zf.writestr("front.html", front)
        zf.writestr("back.html", back)
        zf.writestr("style.css", css)
    return buf.getvalue()


def teardown_module():
    """清理测试目录"""
    shutil.rmtree(TEST_THEMES_DIR, ignore_errors=True)


# ───────────────────── 列出主题 ─────────────────────

class TestListThemes:
    def test_list_builtin_themes(self):
        """列出主题时至少包含 4 个内置主题"""
        resp = client.get("/api/themes")
        assert resp.status_code == 200
        data = resp.json()
        builtin = [t for t in data["themes"] if t["isBuiltin"]]
        assert len(builtin) == 4
        names = {t["name"] for t in builtin}
        assert names == {"default", "minimal", "netflix", "dictionary"}


# ───────────────────── CSS 变量覆盖 ─────────────────────

class TestCssOverrides:
    def test_load_overrides_empty(self):
        """未保存过的主题返回空 variables"""
        resp = client.get("/api/themes/default")
        assert resp.status_code == 200
        assert resp.json()["variables"] == {}

    def test_save_and_load_overrides(self):
        """保存后能加载回相同的变量"""
        vars_ = {"--card-bg": "#1a1a2e", "--card-text": "#ffffff"}
        resp = client.post("/api/themes/minimal", json={"variables": vars_})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True

        resp = client.get("/api/themes/minimal")
        assert resp.status_code == 200
        assert resp.json()["variables"] == vars_

    def test_save_invalid_theme(self):
        """保存到无效主题名返回 400"""
        resp = client.post("/api/themes/nonexistent", json={"variables": {}})
        assert resp.status_code == 400

    def test_delete_overrides(self):
        """删除覆盖后返回空"""
        client.post("/api/themes/netflix", json={"variables": {"--card-bg": "#000"}})
        resp = client.delete("/api/themes/netflix")
        assert resp.status_code == 200
        assert resp.json()["reset"] is True

        resp = client.get("/api/themes/netflix")
        assert resp.json()["variables"] == {}

    def test_load_custom_theme_overrides(self):
        """加载自定义主题时返回 isCustom 标记"""
        # 先导入一个自定义主题
        zip_data = _make_test_zip("mytheme", "My Theme")
        resp = client.post("/api/themes/import", files={"file": ("test.zip", zip_data, "application/zip")})
        assert resp.status_code == 200

        resp = client.get("/api/themes/mytheme")
        assert resp.status_code == 200
        assert resp.json()["isCustom"] is True


# ───────────────────── ZIP 导入 ─────────────────────

class TestImportTheme:
    def test_import_valid_zip(self):
        """导入合法的 ZIP 主题包"""
        zip_data = _make_test_zip()
        resp = client.post(
            "/api/themes/import",
            files={"file": ("test-theme.zip", zip_data, "application/zip")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["name"] == "test-theme"
        assert data["label"] == "Test Theme"

    def test_import_variable_mapping(self):
        """用户友好的小写变量被映射为 Anki 标准字段名"""
        zip_data = _make_test_zip(
            theme_name="varmap",
            front="{{sentence}} | {{#word}}vocab{{/word}}",
            back="{{translation}} | {{^screenshot}}no img{{/screenshot}} | {{annotation}}",
        )
        resp = client.post(
            "/api/themes/import",
            files={"file": ("varmap.zip", zip_data, "application/zip")},
        )
        assert resp.status_code == 200

        # 通过 API 获取文件内容验证变量映射
        resp = client.get("/api/themes/custom/varmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "{{Sentence}}" in data["front"]
        assert "{{#Word}}" in data["front"]
        assert "{{/Word}}" in data["front"]
        assert "{{Translation}}" in data["back"]
        assert "{{^Screenshot}}" in data["back"]
        assert "{{Notes}}" in data["back"]

    def test_import_appears_in_list(self):
        """导入后自定义主题出现在列表中"""
        zip_data = _make_test_zip("list-test", "List Test")
        client.post("/api/themes/import", files={"file": ("t.zip", zip_data, "application/zip")})

        resp = client.get("/api/themes")
        themes = resp.json()["themes"]
        custom = [t for t in themes if t["name"] == "list-test"]
        assert len(custom) == 1
        assert custom[0]["label"] == "List Test"
        assert not custom[0]["isBuiltin"]

    def test_import_missing_file(self):
        """ZIP 缺少必要文件时返回 400"""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr("theme.json", json.dumps({"name": "bad"}))
        resp = client.post(
            "/api/themes/import",
            files={"file": ("bad.zip", buf.getvalue(), "application/zip")},
        )
        assert resp.status_code == 400

    def test_import_conflict_builtin(self):
        """自定义主题名与内置名冲突时返回 400"""
        zip_data = _make_test_zip("default", "Default Override")
        resp = client.post(
            "/api/themes/import",
            files={"file": ("t.zip", zip_data, "application/zip")},
        )
        assert resp.status_code == 400

    def test_import_invalid_name_characters(self):
        """非法主题名（含特殊字符）返回 400"""
        zip_data = _make_test_zip("bad name!", "Bad Name")
        resp = client.post(
            "/api/themes/import",
            files={"file": ("t.zip", zip_data, "application/zip")},
        )
        assert resp.status_code == 400

    def test_import_not_a_zip(self):
        """上传非 ZIP 文件返回 400"""
        resp = client.post(
            "/api/themes/import",
            files={"file": ("test.txt", b"not a zip", "text/plain")},
        )
        assert resp.status_code == 400

    def test_import_overwrite_existing(self):
        """重复导入同名主题会覆盖"""
        zip_data1 = _make_test_zip("overwrite", label="V1")
        zip_data2 = _make_test_zip("overwrite", label="V2")
        client.post("/api/themes/import", files={"file": ("t.zip", zip_data1, "application/zip")})
        client.post("/api/themes/import", files={"file": ("t.zip", zip_data2, "application/zip")})

        resp = client.get("/api/themes")
        themes = [t for t in resp.json()["themes"] if t["name"] == "overwrite"]
        assert len(themes) == 1
        assert themes[0]["label"] == "V2"

    def test_import_corrupt_zip(self):
        """损坏的 ZIP 文件返回 400"""
        resp = client.post(
            "/api/themes/import",
            files={"file": ("bad.zip", b"not a zip file at all", "application/zip")},
        )
        assert resp.status_code == 400


# ───────────────────── 删除自定义主题 ─────────────────────

class TestDeleteCustomTheme:
    def test_delete_custom_theme(self):
        """删除自定义主题成功"""
        zip_data = _make_test_zip("delete-me", "Delete Me")
        client.post("/api/themes/import", files={"file": ("t.zip", zip_data, "application/zip")})

        resp = client.delete("/api/themes/custom/delete-me")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = client.get("/api/themes")
        names = [t["name"] for t in resp.json()["themes"]]
        assert "delete-me" not in names

    def test_delete_builtin_forbidden(self):
        """不能删除内置主题"""
        resp = client.delete("/api/themes/custom/default")
        assert resp.status_code == 400

    def test_delete_nonexistent(self):
        """删除不存在的自定义主题返回 404"""
        resp = client.delete("/api/themes/custom/nonexistent-xyz")
        assert resp.status_code == 404


# ───────────────────── 自定义主题文件获取 ─────────────────────

class TestGetCustomThemeFiles:
    def test_get_files(self):
        """获取自定义主题的模板文件"""
        zip_data = _make_test_zip("getfiles", "Get Files",
            front="<div>front {{sentence}}</div>",
            back="<div>back {{translation}}</div>",
            css="body { margin: 0; }",
        )
        client.post("/api/themes/import", files={"file": ("t.zip", zip_data, "application/zip")})

        resp = client.get("/api/themes/custom/getfiles")
        assert resp.status_code == 200
        data = resp.json()
        assert "front" in data
        assert "back" in data
        assert "css" in data
        assert "{{Sentence}}" in data["front"]
        assert "{{Translation}}" in data["back"]

    def test_get_files_nonexistent(self):
        """获取不存在的自定义主题返回 404"""
        resp = client.get("/api/themes/custom/no-such-theme")
        assert resp.status_code == 404


# ───────────────────── HTML 安全过滤 ─────────────────────

class TestHtmlSanitization:
    def test_script_tags_removed(self):
        """script 标签被过滤"""
        zip_data = _make_test_zip("safe1", front="<div>ok</div><script>alert('xss')</script>")
        resp = client.post("/api/themes/import", files={"file": ("t.zip", zip_data, "application/zip")})
        assert resp.status_code == 200

        resp = client.get("/api/themes/custom/safe1")
        assert resp.status_code == 200
        assert "<script>" not in resp.json()["front"].lower()

    def test_onclick_removed(self):
        """on* 事件属性被过滤"""
        zip_data = _make_test_zip("safe2", front='<div onclick="alert(1)">click</div>')
        resp = client.post("/api/themes/import", files={"file": ("t.zip", zip_data, "application/zip")})
        assert resp.status_code == 200

        resp = client.get("/api/themes/custom/safe2")
        assert resp.status_code == 200
        assert "onclick" not in resp.json()["front"].lower()
