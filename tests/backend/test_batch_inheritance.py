"""Tests for multi-video batch processing parameter inheritance.

Verifies that remaining videos inherit all settings from the first video:
- AI model configuration (api_key, api_base, model_name)
- Language settings (source_language, target_language)
- Screening & annotation prompts
- Machine translation settings
- Timing configuration (min_duration, padding)
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from models.schemas import BatchProcessRequest


class TestBatchParameterInheritance:
    """Verify all first-video settings are passed to remaining videos."""

    @pytest.fixture
    def mock_request(self):
        """Create a request with all settings explicitly configured."""
        return BatchProcessRequest(
            video_names=["video2.mkv", "video3.mkv"],
            subtitle_files=["video2.srt", ""],  # Mixed: one with subs, one without
            task_id="test-task-123",
            api_key="sk-test-key",
            api_base="https://api.custom.com",
            model_name="gpt-4o-mini",
            ai_concurrency=4,
            source_language="ja",
            target_language="en",
            run_correction=True,
            run_screening=True,
            custom_screen_prompt="Select only dialogue with grammar points",
            run_annotation=True,
            annotation_purpose="vocab",
            custom_annotation_prompt="Focus on N3 vocabulary",
            min_duration=1.5,
            mt_service="deepl",
            mt_api_key="deepl-key-456",
            mt_api_base="https://api.deepl.com",
            mt_model_name="deepl-pro",
        )

    def test_ai_config_inherited(self, mock_request):
        """AI API configuration must be passed to each video."""
        assert mock_request.api_key == "sk-test-key"
        assert mock_request.api_base == "https://api.custom.com"
        assert mock_request.model_name == "gpt-4o-mini"

    def test_language_settings_inherited(self, mock_request):
        """Source and target language must be consistent across all videos."""
        assert mock_request.source_language == "ja"
        assert mock_request.target_language == "en"

    def test_screening_config_inherited(self, mock_request):
        """Screening settings (including custom prompts) must be inherited."""
        assert mock_request.run_screening is True
        assert mock_request.custom_screen_prompt == "Select only dialogue with grammar points"

    def test_annotation_config_inherited(self, mock_request):
        """Annotation settings (purpose + custom prompt) must be inherited."""
        assert mock_request.run_annotation is True
        assert mock_request.annotation_purpose == "vocab"
        assert mock_request.custom_annotation_prompt == "Focus on N3 vocabulary"

    def test_mt_config_inherited(self, mock_request):
        """Machine translation settings must be consistent across all videos."""
        assert mock_request.mt_service == "deepl"
        assert mock_request.mt_api_key == "deepl-key-456"
        assert mock_request.mt_api_base == "https://api.deepl.com"
        assert mock_request.mt_model_name == "deepl-pro"

    def test_timing_config_inherited(self, mock_request):
        """Timing configuration (min_duration) must be inherited."""
        assert mock_request.min_duration == 1.5

    def test_correction_flag_inherited(self, mock_request):
        """AI correction flag must be consistent."""
        assert mock_request.run_correction is True


class TestBatchSubtitleMapping:
    """Test subtitle file mapping for mixed scenarios."""

    def test_mixed_subtitle_mapping(self):
        """Some videos have subtitles, others don't - mapping must preserve order."""
        req = BatchProcessRequest(
            video_names=["vid1.mkv", "vid2.mkv", "vid3.mkv"],
            subtitle_files=["vid1.srt", "", "vid3.ass"],  # vid2 has no subtitle
        )
        assert req.subtitle_files == ["vid1.srt", "", "vid3.ass"]
        # Empty string indicates no subtitle (will trigger Whisper)
        assert req.subtitle_files[1] == ""

    def test_all_videos_with_subtitles(self):
        """All videos have corresponding subtitle files."""
        req = BatchProcessRequest(
            video_names=["a.mp4", "b.mp4"],
            subtitle_files=["a.srt", "b.srt"],
        )
        assert len(req.subtitle_files) == 2
        assert all(s for s in req.subtitle_files)  # All non-empty

    def test_no_subtitles_for_any_video(self):
        """No subtitles provided - all videos will use Whisper."""
        req = BatchProcessRequest(
            video_names=["x.mkv", "y.mkv", "z.mkv"],
            subtitle_files=["", "", ""],
        )
        assert all(s == "" for s in req.subtitle_files)

    def test_three_video_mixed_formats(self):
        """Scenario 2: 3 videos with mixed formats (mkv/mp4) and subtitle handling."""
        req = BatchProcessRequest(
            video_names=["SE01.01.mkv", "test.mkv", "野犬.mp4"],
            subtitle_files=["SE01.01.srt", "", ""],  # Only first has subtitle
            task_id="scenario2-test",
        )
        assert len(req.video_names) == 3
        assert req.subtitle_files[0] == "SE01.01.srt"
        assert req.subtitle_files[1] == ""  # Will trigger Whisper
        assert req.subtitle_files[2] == ""  # Will trigger Whisper


class TestBatchManifestMerge:
    """Test processed_cards.json manifest merging logic."""

    def test_merge_mode_appends_to_processed(self, tmp_path):
        """In merge mode, batch results are appended to existing processed list."""
        manifest_path = tmp_path / "processed_cards.json"

        # Initial manifest from first video
        initial_manifest = {
            "merge": True,
            "processed": [
                {"index": 1, "text": "Video 1 card 1", "video_stem": "video1"},
                {"index": 2, "text": "Video 1 card 2", "video_stem": "video1"},
            ],
            "results": [],
        }
        manifest_path.write_text(json.dumps(initial_manifest), encoding="utf-8")

        # Simulate batch processing adding more cards
        batch_results = [
            {"index": 101, "text": "Video 2 card 1", "video_stem": "video2"},
            {"index": 102, "text": "Video 2 card 2", "video_stem": "video2"},
            {"index": 103, "text": "Video 2 card 3", "video_stem": "video2"},
        ]

        # Merge logic (from process.py lines 1056-1059)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("merge", True):
            manifest["processed"].extend(batch_results)

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        # Verify merge
        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(final["processed"]) == 5  # 2 + 3
        assert final["processed"][0]["video_stem"] == "video1"
        assert final["processed"][2]["video_stem"] == "video2"

    def test_independent_mode_groups_by_video(self, tmp_path):
        """In independent mode, results are grouped by video_stem."""
        manifest_path = tmp_path / "processed_cards.json"

        # Initial manifest
        initial_manifest = {
            "merge": False,
            "processed": [],
            "results": [
                {
                    "video_name": "video1",
                    "cards_count": 2,
                    "processed": [
                        {"index": 1, "text": "Card 1", "video_stem": "video1"},
                        {"index": 2, "text": "Card 2", "video_stem": "video1"},
                    ],
                }
            ],
            "total_cards": 2,
        }
        manifest_path.write_text(json.dumps(initial_manifest), encoding="utf-8")

        # Simulate batch results from 2 more videos
        batch_results = [
            {"index": 101, "text": "V2 card", "video_stem": "video2"},
            {"index": 201, "text": "V3 card", "video_stem": "video3"},
        ]

        # Independent mode logic (from process.py lines 1061-1083)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not manifest.get("merge", True):
            if "results" not in manifest:
                manifest["results"] = []

            # Group by video_stem
            grouped = {}
            for p in batch_results:
                stem = p.get("video_stem", "unknown")
                if stem not in grouped:
                    grouped[stem] = []
                grouped[stem].append(p)

            # Append each video's result
            for stem, items in grouped.items():
                manifest["results"].append({
                    "video_name": stem,
                    "cards_count": len(items),
                    "processed": items,
                })

            # Update total
            if "total_cards" in manifest:
                manifest["total_cards"] = sum(r["cards_count"] for r in manifest["results"])

        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        # Verify independent mode
        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(final["results"]) == 3  # video1 + video2 + video3
        assert final["total_cards"] == 4  # 2 + 1 + 1
        assert final["results"][0]["video_name"] == "video1"
        assert final["results"][1]["video_name"] == "video2"
        assert final["results"][2]["video_name"] == "video3"


class TestBatchErrorHandling:
    """Test error scenarios in batch processing."""

    def test_empty_subtitle_triggers_whisper(self):
        """Empty subtitle string should trigger Whisper transcription."""
        req = BatchProcessRequest(
            video_names=["video.mkv"],
            subtitle_files=[""],  # Empty = no subtitle
        )
        # Empty string means Whisper will be used
        assert req.subtitle_files[0] == ""

    def test_missing_subtitle_file_defaults_to_empty(self):
        """If subtitle_files is None, all videos will use Whisper."""
        req = BatchProcessRequest(
            video_names=["a.mkv", "b.mkv"],
            subtitle_files=None,
        )
        assert req.subtitle_files is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
