"""
C4 - resume 端点测试

验证 POST /api/process/resume/{task_id}：
- _completed_stems 从 manifest 推导已完成视频（合并/独立模式）；
- 未知/过期任务 → 404；
- 全部已完成 → nothing_to_resume；
- 存在未完成视频 → 仅重跑剩余视频，复用幂等去重，manifest 补齐。
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from backend.main import app
import api.process as process_module

client = TestClient(app)


def _parse_sse_events(response):
    events = []
    for line in response.iter_lines():
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _make_fake_task(tmp_path, task_id, video_names, completed_stem="first_video", merge=True):
    """构建 temp/{task_id}/videos + output/{task_id}/manifest（completed_stem 已完成）。"""
    temp_dir = tmp_path / "temp"
    videos_dir = temp_dir / task_id / "videos"
    videos_dir.mkdir(parents=True)
    for name in video_names:
        (videos_dir / name).write_bytes(b"fake video")

    output_dir = tmp_path / "output" / task_id
    output_dir.mkdir(parents=True)

    manifest = {"merge": merge}
    if merge:
        manifest["processed"] = [
            {"index": i, "video_stem": completed_stem, "text": f"Card {i}"}
            for i in range(1, 11)
        ]
    else:
        manifest["processed"] = []
        manifest["results"] = [
            {"video_name": completed_stem, "cards_count": 10, "processed": []}
        ]
        manifest["total_cards"] = 10

    (output_dir / "processed_cards.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return temp_dir, output_dir


@pytest.fixture(autouse=True)
def clear_task_store():
    process_module.task_store.clear()
    yield
    process_module.task_store.clear()


@pytest.fixture
def patch_temp_dir(tmp_path):
    original = process_module.TEMP_DIR
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    process_module.TEMP_DIR = temp_dir
    yield temp_dir
    process_module.TEMP_DIR = original


# ─── _completed_stems 单元测试 ──────────────────────────────────


def test_completed_stems_merge_mode(tmp_path):
    _, output_dir = _make_fake_task(tmp_path, "t1", ["a.mp4"], completed_stem="first")
    assert process_module._completed_stems(str(output_dir)) == {"first"}


def test_completed_stems_independent_mode(tmp_path):
    _, output_dir = _make_fake_task(tmp_path, "t2", ["a.mp4"], completed_stem="solo", merge=False)
    assert process_module._completed_stems(str(output_dir)) == {"solo"}


def test_completed_stems_missing_manifest(tmp_path):
    assert process_module._completed_stems(str(tmp_path / "nope")) == set()


# ─── resume 端点测试 ───────────────────────────────────────────


def test_resume_unknown_task_returns_404(patch_temp_dir):
    resp = client.post("/api/process/resume/unknown-id", json={})
    assert resp.status_code == 404


def test_resume_nothing_to_resume_when_all_completed(tmp_path):
    task_id = "resume-done"
    temp_dir, _ = _make_fake_task(tmp_path, task_id, ["v1.mp4"], completed_stem="v1")
    process_module.TEMP_DIR = temp_dir
    process_module.task_store[task_id] = {
        "video_names_order": ["v1.mp4"],
        "status": "completed",
    }

    resp = client.post(f"/api/process/resume/{task_id}", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "nothing_to_resume"
    assert body["remaining"] == []


def test_resume_reruns_only_remaining_videos(tmp_path):
    task_id = "resume-partial"
    # 上传序三个视频，first_video 已完成，v2/v3 待重跑
    temp_dir, output_dir = _make_fake_task(
        tmp_path, task_id, ["v2.mp4", "v3.mp4"], completed_stem="first_video"
    )
    process_module.TEMP_DIR = temp_dir
    process_module.task_store[task_id] = {
        "video_names_order": ["first_video.mp4", "v2.mp4", "v3.mp4"],
        "status": "error",
    }

    processed_videos = []

    def mock_process(**kwargs):
        idx = len(processed_videos)
        stem = "v2" if idx == 0 else "v3"
        processed_videos.append(stem)
        cards = [
            {"index": 1000 * (idx + 1) + j, "text": f"{stem} card {j}",
             "translation": "t", "audio_path": "", "screenshot_path": ""}
            for j in range(3)
        ]
        return cards, stem

    with patch.object(process_module, "_process_video_to_media", side_effect=mock_process):
        resp = client.post(f"/api/process/resume/{task_id}", json={
            "task_id": task_id,
            "subtitle_files": ["", ""],
        })
        events = _parse_sse_events(resp)

    # 只处理了 v2、v3（first_video 跳过）
    assert processed_videos == ["v2", "v3"]

    complete = next(e for e in events if e["type"] == "complete")
    assert complete.get("error") is not True
    assert complete["videos_processed"] == 2

    # manifest 补齐：原 first_video + 新 v2/v3
    manifest = json.loads((output_dir / "processed_cards.json").read_text(encoding="utf-8"))
    stems = {c.get("video_stem") for c in manifest["processed"]}
    assert stems == {"first_video", "v2", "v3"}
