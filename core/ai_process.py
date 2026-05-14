"""
AI 批量处理模块 - 调用 DeepSeek API 进行翻译和注释
"""

import json
import os
import sys
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# 确保项目根目录在 sys.path 中
_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from errors import ClipLingoError, ErrorCode

# 加载 .env 配置
load_dotenv()

LANGUAGE_NAMES = {
    "zh": "中文", "en": "英语", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "it": "意大利语",
    "pt": "葡萄牙语", "ru": "俄语", "ar": "阿拉伯语", "th": "泰语",
    "vi": "越南语", "nl": "荷兰语", "sv": "瑞典语", "pl": "波兰语",
    "tr": "土耳其语", "hi": "印地语", "id": "印尼语", "uk": "乌克兰语",
}

SYSTEM_PROMPT_TEMPLATE = """你是{source_language}学习教材编写专家。为输入的字幕列表的每一条提供{target_language}翻译和知识点注释。

返回格式（JSON对象）：
{{"items": [{{"index": 数字, "include": true, "translation": "{target_language}翻译", "notes": "重点词汇-释义"}}]}}

注意：
- 必须返回一个 JSON 对象，items 是数组
- 每条字幕都必须保留，include 始终为 true
- translation 和 notes 必填，不可为空
- 保持原文顺序输出，每条都必须有 index 字段"""


class AIProcessor:
    """AI 处理器"""

    def __init__(self, api_key: str = None, base_url: str = None, model_name: str = None,
                 source_language: str = "en", target_language: str = "zh"):
        """
        初始化 AI 处理器

        Args:
            api_key: API Key，默认从环境变量读取
            base_url: API 地址，默认 https://api.deepseek.com
            model_name: 模型名称，默认 deepseek-chat
            source_language: 源语言代码，默认 en
            target_language: 目标语言代码，默认 zh
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ClipLingoError(ErrorCode.API_KEY_MISSING)
        self.client = OpenAI(api_key=self.api_key, base_url=base_url or "https://api.deepseek.com")
        self.model_name = model_name or "deepseek-chat"
        src_name = LANGUAGE_NAMES.get(source_language, source_language)
        tgt_name = LANGUAGE_NAMES.get(target_language, target_language)
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            source_language=src_name, target_language=tgt_name
        )

    def process_batch(self, subtitles: list[dict], batch_size: int = 30, system_prompt: str = None) -> list[dict]:
        """
        批量处理字幕

        Args:
            subtitles: 字幕列表，每项包含 index, start_sec, end_sec, text
            batch_size: 每批处理数量
            system_prompt: 自定义系统提示词，默认使用 SYSTEM_PROMPT

        Returns:
            处理结果列表
        """
        results = []
        total_batches = (len(subtitles) + batch_size - 1) // batch_size

        for i in range(0, len(subtitles), batch_size):
            batch = subtitles[i:i + batch_size]
            batch_num = i // batch_size + 1
            print(f"  处理第 {batch_num}/{total_batches} 批 ({len(batch)} 条)...")

            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt or self.system_prompt},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )

                content = response.choices[0].message.content
                parsed = json.loads(content)

                # 处理可能返回的是 {"items": [...]} 或直接是数组
                if isinstance(parsed, dict):
                    if "items" in parsed:
                        results.extend(parsed["items"])
                    elif "results" in parsed:
                        results.extend(parsed["results"])
                    else:
                        # 尝试找第一个数组值
                        for v in parsed.values():
                            if isinstance(v, list):
                                results.extend(v)
                                break
                elif isinstance(parsed, list):
                    results.extend(parsed)

            except Exception as e:
                print(f"    批次处理失败: {e}")
                error_msg = str(e)[:200]
                for item in batch:
                    results.append({
                        "index": item["index"],
                        "skip": True,
                        "translation": "",
                        "notes": "",
                        "reason": f"AI 处理失败: {error_msg}"
                    })

        return results


def process_subtitles_with_ai(subtitles: list, api_key: str = None,
                              api_base: str = None, model_name: str = None,
                              source_language: str = "en", target_language: str = "zh") -> list[dict]:
    """
    批量处理字幕列表

    Args:
        subtitles: Subtitle 对象列表
        api_key: API Key
        api_base: API 地址（可选）
        model_name: 模型名称（可选）
        source_language: 源语言代码（默认 en）
        target_language: 目标语言代码（默认 zh）

    Returns:
        处理后的完整数据列表
    """
    processor = AIProcessor(api_key, api_base, model_name, source_language, target_language)

    # 转换为 dict 列表
    subtitle_dicts = [
        {
            "index": s.index,
            "start_sec": s.start_sec,
            "end_sec": s.end_sec,
            "text": s.text
        }
        for s in subtitles
    ]

    print(f"开始 AI 处理，共 {len(subtitle_dicts)} 条字幕...")
    results = processor.process_batch(subtitle_dicts)

    # 合并原数据和 AI 结果（跳过 AI 处理失败的条目）
    processed = []
    skipped = 0
    for i, sub in enumerate(subtitle_dicts):
        result = results[i] if i < len(results) and isinstance(results[i], dict) else {"skip": True, "reason": "AI 未返回对应结果"}
        if result.get("skip"):
            skipped += 1
            print(f"  [跳过] 第 {sub['index']} 条: {result.get('reason', 'AI 处理失败')}")
            continue
        processed.append({
            "index": sub["index"],
            "start_sec": sub["start_sec"],
            "end_sec": sub["end_sec"],
            "text": sub["text"],
            "translation": result.get("translation", ""),
            "notes": result.get("notes", ""),
            "reason": result.get("reason", "")
        })

    if skipped:
        print(f"AI 注释完成，保留 {len(processed)} 条，跳过 {skipped} 条失败")
    else:
        print(f"AI 注释完成，共 {len(processed)} 条")

    return processed


def process_subtitles_two_phase(
    subtitles: list,
    api_key: str,
    screen_system_prompt: str,
    annotation_system_prompt: str = None,
    api_base: str = None,
    model_name: str = None,
    source_language: str = "en",
    target_language: str = "zh",
) -> list[dict]:
    """
    两阶段 AI 处理：先筛选（include/skip），再注释（translation + notes）

    与前端两阶段工作流对应：
    - 阶段 1：AI 筛选 — 判断每条字幕是否值得学习
    - 阶段 2：AI 注释 — 为筛选通过的条目生成翻译和注释（include 始终为 true）
      如果 annotation_system_prompt 为 None，跳过阶段 2

    Args:
        subtitles: Subtitle 对象列表
        api_key: API Key
        screen_system_prompt: 筛选阶段的完整 system prompt
        annotation_system_prompt: 注释阶段的完整 system prompt（None 则只筛选不注释）
        api_base: API 地址
        model_name: 模型名称
        source_language: 源语言代码
        target_language: 目标语言代码

    Returns:
        两阶段处理后的完整数据列表（仅包含筛选通过 + 注释成功的条目）
    """
    processor = AIProcessor(api_key, api_base, model_name, source_language, target_language)

    subtitle_dicts = [
        {"index": s.index, "start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text}
        for s in subtitles
    ]

    # ── 阶段 1：AI 筛选 ──
    print(f"开始 AI 筛选，共 {len(subtitle_dicts)} 条字幕...")
    screen_results = processor.process_batch(subtitle_dicts, system_prompt=screen_system_prompt)

    included: list[tuple] = []
    skipped = 0
    for sub, result in zip(subtitle_dicts, screen_results):
        if isinstance(result, dict) and result.get("include"):
            included.append((sub, result))
        else:
            skipped += 1
            reason = result.get("reason", "") if isinstance(result, dict) else "无结果"
            print(f"  [筛选跳过] 第 {sub['index']} 条: {reason}")

    if skipped:
        print(f"AI 筛选完成，保留 {len(included)} 条，跳过 {skipped} 条")

    if not included:
        return []

    # 如果用户只想要筛选，跳过注释阶段
    if annotation_system_prompt is None:
        processed = []
        for sub, screen_result in included:
            processed.append({
                "index": sub["index"],
                "start_sec": sub["start_sec"],
                "end_sec": sub["end_sec"],
                "text": sub["text"],
                "translation": "",
                "notes": "",
                "word": "",
                "definition": "",
                "reason": screen_result.get("reason", "") if isinstance(screen_result, dict) else "",
            })
        print(f"AI 筛选完成（仅筛选），保留 {len(processed)} 条")
        return processed

    # ── 阶段 2：AI 注释 ──
    included_subs = [s for s, _ in included]
    print(f"开始 AI 注释，共 {len(included_subs)} 条字幕...")
    annotate_results = processor.process_batch(included_subs, system_prompt=annotation_system_prompt)

    processed = []
    for (sub, screen_result), annotate_result in zip(included, annotate_results):
        if isinstance(annotate_result, dict) and not annotate_result.get("skip"):
            processed.append({
                "index": sub["index"],
                "start_sec": sub["start_sec"],
                "end_sec": sub["end_sec"],
                "text": annotate_result.get("corrected_text") or sub["text"],
                "translation": annotate_result.get("translation", ""),
                "notes": annotate_result.get("notes", ""),
                "word": annotate_result.get("word", ""),
                "definition": annotate_result.get("definition", ""),
                "reason": screen_result.get("reason", "") if isinstance(screen_result, dict) else "",
            })

    print(f"AI 两阶段处理完成，共 {len(processed)} 条")
    return processed


if __name__ == '__main__':
    # 测试
    import os
    os.environ["DEEPSEEK_API_KEY"] = "test-key"
    processor = AIProcessor()
    print("AIProcessor 已初始化")