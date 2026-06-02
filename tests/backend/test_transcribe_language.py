import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(TEST_ROOT / "backend"))

from api.transcribe import _asr_subprocess, _normalize_language


class FakePipe:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_normalize_language_converts_blank_to_none():
    assert _normalize_language(None) is None
    assert _normalize_language("") is None
    assert _normalize_language("   ") is None
    assert _normalize_language(" en ") == "en"


def test_faster_whisper_transcribe_receives_none_for_blank_language(tmp_path):
    model = MagicMock()
    segment = SimpleNamespace(start=0.0, end=1.2, text=" Hello ")
    model.transcribe.return_value = (iter([segment]), object())
    pipe = FakePipe()

    with (
        patch("core.media_cut.get_video_duration", return_value=2.0),
        patch("core.whisper_manager.load_model", return_value=model),
        patch("core.whisper_transcribe.save_as_srt"),
    ):
        _asr_subprocess(
            video_path=str(tmp_path / "video.mp4"),
            srt_path=str(tmp_path / "out.srt"),
            asr_engine="faster_whisper",
            model_name="base",
            language="",
            result_path=str(tmp_path / "result.json"),
            progress_pipe=pipe,
        )

    model.transcribe.assert_called_once()
    assert model.transcribe.call_args.kwargs["language"] is None
    assert any(message.get("step") == "done" for message in pipe.messages)
