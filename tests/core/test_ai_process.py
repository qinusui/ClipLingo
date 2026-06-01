"""
ai_process 模块测试
覆盖：AIProcessor 初始化、process_batch 各场景、两阶段处理、异常处理
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from core.ai_process import (
    AIProcessor, process_subtitles_with_ai, process_subtitles_two_phase,
    SYSTEM_PROMPT_TEMPLATE, LANGUAGE_NAMES,
)
from errors import ClipLingoError, ErrorCode


# ── 辅助 ────────────────────────────────────────────────

@dataclass
class FakeSubtitle:
    """模拟 Subtitle 对象"""
    index: int
    start_sec: float
    end_sec: float
    text: str


def _make_subtitles(n: int = 3) -> list[FakeSubtitle]:
    return [
        FakeSubtitle(i + 1, float(i * 2), float(i * 2 + 2), f"Text {i + 1}")
        for i in range(n)
    ]


def _mock_openai_response(items: list[dict]) -> Mock:
    """构造模拟的 OpenAI 响应"""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = json.dumps({"items": items}, ensure_ascii=False)
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AIProcessor.__init__
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestAIProcessorInit:
    """AI 处理器初始化"""

    def test_init_with_explicit_key(self):
        """显式传入 API Key"""
        proc = AIProcessor(api_key="test-key")
        assert proc.api_key == "test-key"
        assert proc.model_name == "deepseek-chat"

    def test_init_from_env(self, monkeypatch):
        """从环境变量读取 API Key"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        proc = AIProcessor()
        assert proc.api_key == "env-key"

    def test_init_missing_key_raises(self, monkeypatch):
        """缺少 API Key 应抛出 ClipLingoError"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with pytest.raises(ClipLingoError) as exc_info:
            AIProcessor(api_key=None)
        assert exc_info.value.code == ErrorCode.API_KEY_MISSING

    def test_init_custom_model(self):
        """自定义模型名称"""
        proc = AIProcessor(api_key="k", model_name="gpt-4")
        assert proc.model_name == "gpt-4"

    def test_init_custom_languages(self):
        """自定义源/目标语言"""
        proc = AIProcessor(api_key="k", source_language="ja", target_language="en")
        assert "日语" in proc.system_prompt
        assert "英语" in proc.system_prompt

    def test_init_unknown_language_uses_code(self):
        """未知语言代码应直接使用代码本身"""
        proc = AIProcessor(api_key="k", source_language="xx", target_language="yy")
        assert "xx" in proc.system_prompt
        assert "yy" in proc.system_prompt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AIProcessor.process_batch
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestProcessBatch:
    """批量处理"""

    @patch("core.ai_process.OpenAI")
    def test_normal_batch(self, mock_openai_cls):
        """正常批次处理"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        items = [
            {"index": 1, "include": True, "translation": "译文1", "notes": "注释1"},
            {"index": 2, "include": True, "translation": "译文2", "notes": "注释2"},
        ]
        mock_client.chat.completions.create.return_value = _mock_openai_response(items)

        proc = AIProcessor(api_key="k")
        subs = [
            {"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hello"},
            {"index": 2, "start_sec": 2, "end_sec": 4, "text": "World"},
        ]
        result = proc.process_batch(subs)

        assert len(result) == 2
        assert result[0]["translation"] == "译文1"

    @patch("core.ai_process.OpenAI")
    def test_empty_subtitles(self, mock_openai_cls):
        """空字幕列表应返回空结果"""
        proc = AIProcessor(api_key="k")
        result = proc.process_batch([])
        assert result == []

    @patch("core.ai_process.OpenAI")
    def test_multiple_batches(self, mock_openai_cls):
        """多批次处理"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        def mock_create(**kwargs):
            # 根据输入返回对应数量的结果
            user_content = json.loads(kwargs["messages"][1]["content"])
            items = [{"index": s["index"], "include": True, "translation": f"T{s['index']}", "notes": ""} for s in user_content]
            return _mock_openai_response(items)

        mock_client.chat.completions.create.side_effect = mock_create

        proc = AIProcessor(api_key="k")
        subs = [{"index": i, "start_sec": 0, "end_sec": 2, "text": f"T{i}"} for i in range(1, 6)]
        result = proc.process_batch(subs, batch_size=2)

        assert len(result) == 5

    @patch("core.ai_process.OpenAI")
    def test_api_returns_results_key(self, mock_openai_cls):
        """API 返回 results 而非 items"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message.content = json.dumps({"results": [{"index": 1, "translation": "T"}]})
        mock_client.chat.completions.create.return_value = response

        proc = AIProcessor(api_key="k")
        result = proc.process_batch([{"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hi"}])
        assert len(result) == 1

    @patch("core.ai_process.OpenAI")
    def test_api_returns_list(self, mock_openai_cls):
        """API 直接返回数组"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message.content = json.dumps([{"index": 1, "translation": "T"}])
        mock_client.chat.completions.create.return_value = response

        proc = AIProcessor(api_key="k")
        result = proc.process_batch([{"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hi"}])
        assert len(result) == 1

    @patch("core.ai_process.OpenAI")
    def test_api_exception_marks_skip(self, mock_openai_cls):
        """API 异常应标记 skip"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        proc = AIProcessor(api_key="k")
        subs = [{"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hi"}]
        result = proc.process_batch(subs)

        assert len(result) == 1
        assert result[0]["skip"] is True
        assert "API Error" in result[0]["reason"]

    @patch("core.ai_process.OpenAI")
    def test_custom_system_prompt(self, mock_openai_cls):
        """自定义系统提示词"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_openai_response([{"index": 1, "translation": "T"}])

        proc = AIProcessor(api_key="k")
        proc.process_batch([{"index": 1, "start_sec": 0, "end_sec": 2, "text": "Hi"}], system_prompt="CUSTOM PROMPT")

        call_args = mock_client.chat.completions.create.call_args
        assert call_args[1]["messages"][0]["content"] == "CUSTOM PROMPT"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  process_subtitles_with_ai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestProcessSubtitlesWithAI:
    """合并处理函数"""

    @patch("core.ai_process.OpenAI")
    def test_normal_merge(self, mock_openai_cls):
        """正常合并结果"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        items = [
            {"index": 1, "translation": "你好", "notes": "词汇"},
            {"index": 2, "translation": "世界", "notes": ""},
        ]
        mock_client.chat.completions.create.return_value = _mock_openai_response(items)

        subs = _make_subtitles(2)
        result = process_subtitles_with_ai(subs, api_key="k")

        assert len(result) == 2
        assert result[0]["text"] == "Text 1"
        assert result[0]["translation"] == "你好"

    @patch("core.ai_process.OpenAI")
    def test_skip_failed_items(self, mock_openai_cls):
        """跳过 AI 处理失败的条目"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        items = [
            {"index": 1, "skip": True, "translation": "", "notes": "", "reason": "失败"},
            {"index": 2, "translation": "世界", "notes": ""},
        ]
        mock_client.chat.completions.create.return_value = _mock_openai_response(items)

        subs = _make_subtitles(2)
        result = process_subtitles_with_ai(subs, api_key="k")

        assert len(result) == 1
        assert result[0]["index"] == 2


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  process_subtitles_two_phase
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestProcessSubtitlesTwoPhase:
    """两阶段处理"""

    @patch("core.ai_process.OpenAI")
    def test_two_phase_normal(self, mock_openai_cls):
        """两阶段正常流程"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        # 阶段1：筛选（全部 include）
        screen_items = [
            {"index": 1, "include": True, "reason": "useful"},
            {"index": 2, "include": False, "reason": "too simple"},
            {"index": 3, "include": True, "reason": "useful"},
        ]
        # 阶段2：注释
        annotate_items = [
            {"index": 1, "translation": "译文1", "notes": "注释1", "word": "word1", "definition": "def1"},
            {"index": 3, "translation": "译文3", "notes": "注释3", "word": "word3", "definition": "def3"},
        ]

        mock_client.chat.completions.create.side_effect = [
            _mock_openai_response(screen_items),
            _mock_openai_response(annotate_items),
        ]

        subs = _make_subtitles(3)
        result = process_subtitles_two_phase(
            subs, api_key="k",
            screen_system_prompt="SCREEN",
            annotation_system_prompt="ANNOTATE",
        )

        assert len(result) == 2
        assert result[0]["text"] == "Text 1"
        assert result[0]["translation"] == "译文1"

    @patch("core.ai_process.OpenAI")
    def test_screen_only_when_annotation_none(self, mock_openai_cls):
        """annotation_system_prompt=None 时只做筛选"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        screen_items = [
            {"index": 1, "include": True, "reason": "good"},
        ]
        mock_client.chat.completions.create.return_value = _mock_openai_response(screen_items)

        subs = _make_subtitles(1)
        result = process_subtitles_two_phase(
            subs, api_key="k",
            screen_system_prompt="SCREEN",
            annotation_system_prompt=None,  # 只筛选
        )

        assert len(result) == 1
        assert result[0]["translation"] == ""  # 无注释
        assert mock_client.chat.completions.create.call_count == 1  # 只调用一次

    @patch("core.ai_process.OpenAI")
    def test_all_screened_out_returns_empty(self, mock_openai_cls):
        """全部被筛掉应返回空列表"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        screen_items = [
            {"index": 1, "include": False, "reason": "skip"},
            {"index": 2, "include": False, "reason": "skip"},
        ]
        mock_client.chat.completions.create.return_value = _mock_openai_response(screen_items)

        subs = _make_subtitles(2)
        result = process_subtitles_two_phase(
            subs, api_key="k",
            screen_system_prompt="SCREEN",
            annotation_system_prompt="ANNOTATE",
        )

        assert result == []

    @patch("core.ai_process.OpenAI")
    def test_annotate_skip_items_excluded(self, mock_openai_cls):
        """注释阶段标记 skip 的条目不应出现在结果中"""
        mock_client = Mock()
        mock_openai_cls.return_value = mock_client

        screen_items = [
            {"index": 1, "include": True},
            {"index": 2, "include": True},
        ]
        annotate_items = [
            {"index": 1, "skip": True, "translation": "", "notes": ""},
            {"index": 2, "translation": "好", "notes": "注释"},
        ]

        mock_client.chat.completions.create.side_effect = [
            _mock_openai_response(screen_items),
            _mock_openai_response(annotate_items),
        ]

        subs = _make_subtitles(2)
        result = process_subtitles_two_phase(
            subs, api_key="k",
            screen_system_prompt="SCREEN",
            annotation_system_prompt="ANNOTATE",
        )

        assert len(result) == 1
        assert result[0]["index"] == 2
