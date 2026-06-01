"""
cards API 端点测试
覆盖：列出卡片、预览卡片、下载文件
"""

import sys
from pathlib import Path

# 设置路径
TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(TEST_ROOT / "backend"))

import pytest
import zipfile
import sqlite3
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from api import cards as cards_module

app = FastAPI()
app.include_router(cards_module.router, prefix="/api/cards")


@pytest.fixture
def client():
    return TestClient(app)


# ── 辅助 ────────────────────────────────────────────────

def _create_mock_apkg(path: Path, num_cards: int = 3):
    """创建模拟的 .apkg 文件（zip + sqlite）"""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmp_dir:
        # 创建 SQLite 数据库
        db_path = Path(tmp_dir) / "collection.anki2"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 创建 cards 和 notes 表
        cursor.execute("""
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY,
                note_id INTEGER,
                ord INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY,
                flds TEXT
            )
        """)

        # 插入测试数据
        for i in range(num_cards):
            note_id = i + 1
            cursor.execute("INSERT INTO notes (id, flds) VALUES (?, ?)",
                         (note_id, f"Sentence {i}\x1fTranslation {i}\x1fNotes {i}"))
            cursor.execute("INSERT INTO cards (id, note_id, ord) VALUES (?, ?, ?)",
                         (i + 1, note_id, i))

        conn.commit()
        conn.close()

        # 打包为 zip
        with zipfile.ZipFile(path, 'w') as zf:
            zf.write(db_path, "collection.anki2")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /list
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestListCards:
    """列出 APKG 中的卡片"""

    def test_list_cards_normal(self, client, tmp_path):
        """正常列出卡片"""
        apkg_path = tmp_path / "test.apkg"
        _create_mock_apkg(apkg_path, num_cards=3)

        resp = client.get("/api/cards/list", params={"apkg_path": str(apkg_path)})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["cards"]) == 3

    def test_list_cards_fields(self, client, tmp_path):
        """卡片应包含正确字段"""
        apkg_path = tmp_path / "test.apkg"
        _create_mock_apkg(apkg_path, num_cards=1)

        resp = client.get("/api/cards/list", params={"apkg_path": str(apkg_path)})
        card = resp.json()["cards"][0]

        assert "id" in card
        assert "note_id" in card
        assert "fields" in card
        assert isinstance(card["fields"], list)

    def test_list_cards_file_not_found(self, client):
        """APKG 文件不存在"""
        resp = client.get("/api/cards/list", params={"apkg_path": "/nonexistent/test.apkg"})

        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_list_cards_empty_apkg(self, client, tmp_path):
        """空 APKG 文件"""
        apkg_path = tmp_path / "empty.apkg"
        _create_mock_apkg(apkg_path, num_cards=0)

        resp = client.get("/api/cards/list", params={"apkg_path": str(apkg_path)})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert len(data["cards"]) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /preview
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestPreviewCards:
    """预览卡片"""

    def test_preview_normal(self, client):
        """正常预览"""
        cards = [
            {
                "sentence": "Hello world",
                "translation": "你好世界",
                "notes": "词汇注释",
                "start_sec": 0.0,
                "end_sec": 2.0,
            }
        ]
        resp = client.post("/api/cards/preview", json=cards)

        assert resp.status_code == 200
        assert "html" in resp.json()
        assert "Hello world" in resp.json()["html"]

    def test_preview_multiple_cards(self, client):
        """多卡片预览"""
        cards = [
            {
                "sentence": f"Sentence {i}",
                "translation": f"翻译 {i}",
                "notes": f"注释 {i}",
                "start_sec": float(i),
                "end_sec": float(i + 2),
            }
            for i in range(5)
        ]
        resp = client.post("/api/cards/preview", json=cards)

        assert resp.status_code == 200
        html = resp.json()["html"]
        assert "Sentence 0" in html

    def test_preview_limit_to_10(self, client):
        """预览最多只显示 10 张"""
        cards = [
            {
                "sentence": f"S{i}",
                "translation": f"T{i}",
                "notes": f"N{i}",
                "start_sec": float(i),
                "end_sec": float(i + 1),
            }
            for i in range(15)
        ]
        resp = client.post("/api/cards/preview", json=cards)

        assert resp.status_code == 200
        html = resp.json()["html"]
        # 应显示"还有 X 张"
        assert "还有" in html

    def test_preview_empty_list(self, client):
        """空卡片列表"""
        resp = client.post("/api/cards/preview", json=[])

        assert resp.status_code == 200
        assert "html" in resp.json()
