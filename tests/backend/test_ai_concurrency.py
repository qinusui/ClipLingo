"""测试 AI 并发数配置功能"""
import pytest
import pydantic
from models.schemas import AIRecommendRequest, AIAnnotateRequest, SubtitleItem


def _make_subtitles(count=5):
    return [
        SubtitleItem(index=i, start_sec=float(i), end_sec=float(i + 1), text=f"sentence {i}")
        for i in range(count)
    ]


class TestAIConcurrencySchema:
    """验证 AIRecommendRequest / AIAnnotateRequest 的 ai_concurrency 字段"""

    def test_default_is_3(self):
        req = AIRecommendRequest(subtitles=_make_subtitles())
        assert req.ai_concurrency == 3

    def test_custom_value_accepted(self):
        req = AIRecommendRequest(subtitles=_make_subtitles(), ai_concurrency=7)
        assert req.ai_concurrency == 7

    def test_min_boundary(self):
        req = AIRecommendRequest(subtitles=_make_subtitles(), ai_concurrency=1)
        assert req.ai_concurrency == 1

    def test_max_boundary(self):
        req = AIRecommendRequest(subtitles=_make_subtitles(), ai_concurrency=20)
        assert req.ai_concurrency == 20

    def test_below_min_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            AIRecommendRequest(subtitles=_make_subtitles(), ai_concurrency=0)

    def test_above_max_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            AIRecommendRequest(subtitles=_make_subtitles(), ai_concurrency=21)

    def test_annotate_request_same_field(self):
        req = AIAnnotateRequest(subtitles=_make_subtitles())
        assert req.ai_concurrency == 3
        req2 = AIAnnotateRequest(subtitles=_make_subtitles(), ai_concurrency=5)
        assert req2.ai_concurrency == 5
