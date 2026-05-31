"""提示词构建 — 模板常量 + build_*prompt() 函数"""

from .language_names import get_name

# ── Legacy full recommend prompt (not used by two-phase workflow but kept for compatibility) ──

DEFAULT_CRITERIA = """你是{source_language}学习教材编写专家。对输入的字幕列表，每条判断是否值得作为学习材料：

判断标准：
- 有明确的语法知识点（如时态、从句、虚拟语气等）
- 有实用表达或固定搭配
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）
- 有文化背景或情境意义"""


# ── 两阶段 AI：筛选专用提示词 ──

SCREENING_CRITERIA = """你是{source_language}学习材料筛选专家。对输入的字幕列表，每条判断是否值得作为学习材料：

判断标准：
- 有明确的语法知识点（如时态、从句、虚拟语气等）
- 有实用表达或固定搭配
- 对话内容有意义（非简单寒暄如'okay', 'yeah', 'uh-huh'等）
- 有文化背景或情境意义"""

SCREENING_RETURN_FORMAT = """

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "include": true/false, "reason": "简短原因"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- include=true 表示值得加入学习
- include=false 时 reason 说明原因（如：纯简单应答、无知识价值）
- 保持原文顺序输出，每条都必须有 index 字段"""

SCREENING_CORRECT_TEXT_EXTRA = """
- 如果原文有明显转录错误（拼写错误、漏词、误识别），请在 corrected_text 字段中提供修正后的文本；如无错误则省略此字段"""


# ── 两阶段 AI：注释专用提示词 ──

ANNOTATION_GRAMMAR_CRITERIA = """你是{source_language}学习教材编写专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和语法句型注释。

每条字幕可能附带 prev_text（前一句原文）和 next_text（后一句原文），用于理解语境、解析指代和省略——请参考上下文但只翻译和注释当前句。"""

ANNOTATION_VOCAB_CRITERIA = """你是{target_language}词汇教学专家。为输入的字幕列表（已筛选为值得学习的内容）提供翻译和词汇注释。

每条字幕可能附带 prev_text（前一句原文）和 next_text（后一句原文），用于理解语境、解析指代和省略——请参考上下文但只翻译和注释当前句."""

ANNOTATION_GRAMMAR_RETURN_FORMAT = """
返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "语法知识点和实用表达", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 应侧重语法结构和实用表达
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出"""

ANNOTATION_VOCAB_RETURN_FORMAT = """
返回格式（严格遵守）：
{{"items": [{{"index": 数字, "translation": "{target_language}翻译", "notes": "重点单词-词性-释义", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 所有项目必须包含 translation、notes、word、definition
- notes 格式：重点单词-词性-释义；遇词组则整体标注
- word 为句子中最值得背诵的核心单词或词组
- 保持原文顺序输出"""


def build_screening_prompt(
    custom_prompt: str | None = None,
    source_language: str = "en",
    target_language: str = "zh",
    correct_text: bool = False,
) -> str:
    """构建筛选专用提示词（只判断 include/reason，不返回翻译注释）"""
    src_name = get_name(source_language)
    tgt_name = get_name(target_language)
    criteria = custom_prompt if custom_prompt else SCREENING_CRITERIA.format(source_language=src_name)
    fmt = SCREENING_RETURN_FORMAT.format(target_language=tgt_name)
    if correct_text:
        fmt += SCREENING_CORRECT_TEXT_EXTRA
    return criteria + fmt


def build_system_prompt(
    custom_prompt: str | None = None,
    source_language: str = "en",
    target_language: str = "zh",
) -> str:
    """组合用户自定义的判断标准与固定的返回格式（legacy full-recommend mode）"""
    src_name = get_name(source_language)
    tgt_name = get_name(target_language)
    if custom_prompt:
        criteria = custom_prompt
    else:
        criteria = DEFAULT_CRITERIA.format(source_language=src_name)
    formatted_format = RETURN_FORMAT.format(target_language=tgt_name)
    return criteria + formatted_format


RETURN_FORMAT = """

返回格式（严格遵守）：
{{"items": [{{"index": 数字, "include": true/false, "reason": "简短原因", "translation": "{target_language}翻译", "notes": "重点词汇-释义", "word": "句子中最值得学习的核心单词或词组", "definition": "该单词/词组的{target_language}释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- include=true 表示值得加入学习
- include=false 时 reason 说明原因（如：纯简单应答、无知识价值）
- 只对 include=true 的句子提供 translation、notes、word、definition
- word 为句子中最值得背诵的核心单词或词组，definition 为其释义
- 如果句子没有明确的核心单词，word 和 definition 可以与 notes 中的重点词汇一致
- 保持原文顺序输出，每条都必须有 index 字段"""


def build_annotation_prompt(
    purpose: str,
    source_language: str = "en",
    target_language: str = "zh",
    custom_criteria: str | None = None,
) -> str:
    """构建注释专用提示词：用户标准 + 后端追加固定返回格式"""
    src_name = get_name(source_language)
    tgt_name = get_name(target_language)
    if purpose == "vocab":
        criteria = custom_criteria if custom_criteria else ANNOTATION_VOCAB_CRITERIA
        criteria = criteria.format(source_language=src_name, target_language=tgt_name)
        return_format = ANNOTATION_VOCAB_RETURN_FORMAT.format(target_language=tgt_name)
    else:
        criteria = custom_criteria if custom_criteria else ANNOTATION_GRAMMAR_CRITERIA
        criteria = criteria.format(source_language=src_name, target_language=tgt_name)
        return_format = ANNOTATION_GRAMMAR_RETURN_FORMAT.format(target_language=tgt_name)
    return criteria + return_format
