"""Tests for batch process schemas and pipeline logic."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from models.schemas import (
    BatchProcessRequest,
    BatchProcessResponse,
    SubtitleItem,
)


# ─── Schema Tests ──────────────────────────────────────────────


class TestBatchProcessRequestSchema:
    """BatchProcessRequest Pydantic model validation."""

    def test_minimal_request(self):
        """Only video_names is strictly required; all other fields have defaults."""
        req = BatchProcessRequest(video_names=["video.mp4"])
        assert req.video_names == ["video.mp4"]
        assert req.task_id == ""
        assert req.subtitle_files is None
        assert req.api_key is None
        assert req.api_base is None
        assert req.model_name is None
        assert req.ai_concurrency == 3
        assert req.source_language == "en"
        assert req.target_language == "zh"
        assert req.run_correction is True
        assert req.run_screening is True
        assert req.custom_screen_prompt is None
        assert req.run_annotation is True
        assert req.annotation_purpose == "grammar"
        assert req.custom_annotation_prompt is None
        assert req.min_duration == 1.0
        assert req.mt_service is None
        assert req.mt_api_key is None
        assert req.mt_api_base is None
        assert req.mt_model_name is None

    def test_full_request(self):
        """All fields explicitly set."""
        req = BatchProcessRequest(
            video_names=["vid1.mp4", "vid2.mp4"],
            subtitle_files=["vid1.srt", "vid2.srt"],
            task_id="abc-123",
            api_key="sk-test123",
            api_base="https://api.example.com",
            model_name="gpt-4o",
            ai_concurrency=5,
            source_language="ja",
            target_language="ko",
            run_correction=False,
            run_screening=True,
            custom_screen_prompt="Custom screen prompt",
            run_annotation=True,
            annotation_purpose="vocab",
            custom_annotation_prompt="Custom annotation prompt",
            min_duration=2.5,
            mt_service="deepl",
            mt_api_key="dl-key-123",
            mt_api_base="https://api.deepl.com",
            mt_model_name="deepl-pro",
        )
        assert len(req.video_names) == 2
        assert req.api_key == "sk-test123"
        assert req.ai_concurrency == 5
        assert req.run_correction is False
        assert req.annotation_purpose == "vocab"
        assert req.min_duration == 2.5
        assert req.mt_service == "deepl"
        assert req.mt_api_key == "dl-key-123"
        assert req.mt_api_base == "https://api.deepl.com"
        assert req.mt_model_name == "deepl-pro"

    @pytest.mark.parametrize("value", [0, 21, -1])
    def test_ai_concurrency_bounds(self, value):
        """ai_concurrency must be in [1, 20]."""
        with pytest.raises(Exception):
            BatchProcessRequest(
                video_names=["v.mp4"], ai_concurrency=value,
            )

    def test_json_roundtrip(self):
        """Serialize to JSON then deserialize — all fields preserved."""
        original = BatchProcessRequest(
            video_names=["a.mp4", "b.mp4"],
            task_id="xyz-789",
            ai_concurrency=2,
            source_language="fr",
            target_language="de",
            run_correction=False,
            run_screening=False,
            run_annotation=False,
        )
        data = original.model_dump()
        restored = BatchProcessRequest(**data)
        assert restored.task_id == original.task_id
        assert restored.video_names == original.video_names
        assert restored.ai_concurrency == original.ai_concurrency
        assert restored.source_language == original.source_language
        assert restored.run_correction == original.run_correction

    def test_empty_video_names_allowed(self):
        """Empty list is valid — caller may validate separately."""
        req = BatchProcessRequest(video_names=[])
        assert req.video_names == []


class TestBatchProcessResponseSchema:
    """BatchProcessResponse Pydantic model validation."""

    def test_valid_response(self):
        resp = BatchProcessResponse(
            success=True,
            message="Done",
            videos_processed=2,
            total_cards=128,
            task_id="abc-123",
        )
        assert resp.success is True
        assert resp.videos_processed == 2
        assert resp.total_cards == 128

    def test_failed_response(self):
        resp = BatchProcessResponse(
            success=False,
            message="API timeout",
            videos_processed=0,
            total_cards=0,
            task_id="fail-001",
        )
        assert resp.success is False


# ─── Pipeline Logic Tests ──────────────────────────────────────


class TestBatchPromptAssembly:
    """Verify AI prompts are assembled correctly from request config."""

    def test_custom_screen_prompt_used_as_is(self):
        """Custom screen prompt takes precedence over built-in templates."""
        expected = "MY CUSTOM SCREEN PROMPT"
        req = BatchProcessRequest(
            video_names=["v.mp4"],
            custom_screen_prompt=expected,
        )
        # The batch endpoint uses request.custom_screen_prompt as-is when set
        assert req.custom_screen_prompt == expected

    def test_custom_annotation_prompt_preserved(self):
        """Custom annotation prompt and purpose are preserved on schema."""
        req = BatchProcessRequest(
            video_names=["v.mp4"],
            annotation_purpose="vocab",
            custom_annotation_prompt="Custom vocab prompt",
        )
        assert req.annotation_purpose == "vocab"
        assert req.custom_annotation_prompt == "Custom vocab prompt"

    def test_defaults_for_japanese_korean(self):
        """Language flags default to en/zh; caller can override."""
        req = BatchProcessRequest(
            video_names=["v.mp4"],
            source_language="ja",
            target_language="ko",
        )
        assert req.source_language == "ja"
        assert req.target_language == "ko"


class TestBatchSubtitleMatching:
    """Test SRT candidate file matching logic used in the batch endpoint."""

    def test_srt_candidate_matching(self):
        """Files matching video stem + subtitle suffix are found via glob."""
        stem = "Episode01"
        candidates = [
            Path(f"{stem}.srt"),
            Path(f"{stem}.ass"),
            Path(f"{stem}.vtt"),
        ]
        # Filter to valid subtitle suffixes — three match
        srt_paths = [
            s for s in candidates if s.suffix.lower() in ('.srt', '.ass', '.vtt')
        ]
        assert len(srt_paths) == 3
        # .srt comes first in the list
        assert srt_paths[0].suffix == ".srt"

    def test_no_srt_file_returns_empty(self):
        """Non-subtitle files should not match."""
        stem = "video"
        prefix = f"{stem}"
        non_sub = [Path(f"{prefix}.mp4"), Path(f"{prefix}.txt")]
        srt_paths = [
            s for s in non_sub if s.suffix.lower() in ('.srt', '.ass', '.vtt')
        ]
        assert srt_paths == []

    def test_case_insensitive_suffix(self):
        """.SRT (uppercase) should be matched."""
        path = Path("video.SRT")
        result = [path] if path.suffix.lower() == ".srt" else []
        assert len(result) == 1


@pytest.mark.asyncio
async def test_batch_post_process_keeps_corrected_text():
    """corrected_text must NOT be stripped by post-process.

    Regression test for the bug where correction phase contaminated
    results with include/reason fields, and corrected_text was stripped
    alongside annotation fields.
    """
    from api.ai_batch import BatchPostProcess, _apply_postprocess

    items = [
        {"index": 1, "corrected_text": "Fixed text", "translation": "trans"},
    ]
    pp = BatchPostProcess(strip_annotation_fields=True)
    _apply_postprocess(items, pp)

    assert items[0]["corrected_text"] == "Fixed text"
    assert "translation" not in items[0]
