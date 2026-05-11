"""
ClipLingo - 主程序
将视频和字幕文件转换为可导入 Anki 的牌组
"""

import os
import sys

# ── 最早阶段：强制 UTF-8 模式（解决中文路径问题） ──
if sys.platform == "win32":
    if not os.environ.get("PYTHONIOENCODING"):
        os.environ["PYTHONIOENCODING"] = "utf-8"
    if not os.environ.get("PYTHONUTF8"):
        os.environ["PYTHONUTF8"] = "1"
    for _name in ("stdout", "stderr", "stdin"):
        _stream = getattr(sys, _name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import json
from pathlib import Path

# 处理 --version 参数（在导入模块之前，避免依赖问题）
if "--version" in sys.argv:
    print("ClipLingo 1.4.0")
    sys.exit(0)

from core.parse_srt import parse_srt, filter_short_subtitles, Subtitle
from core.ai_process import process_subtitles_with_ai
from core.media_cut import process_media_items
from core.pack_apkg import create_apkg


def _apply_index_offset(items: list[dict], offset: int) -> list[dict]:
    """给所有条目的 index 加偏移量，避免多视频合并时文件名冲突"""
    if offset == 0:
        return items
    for item in items:
        item["index"] = item.get("index", 0) + offset
    return items


def _process_video_to_media(
    video_path: str,
    subtitle_path: str | None,
    output_dir: str,
    index_offset: int = 0,
    api_key: str = None,
    min_duration: float = 1.0,
    num_workers: int = 8,
    whisper_model: str = "base",
    language: str = None,
    force_transcribe: bool = False,
    progress_callback=None,
    pre_processed: list = None,
    api_base: str = None,
    model_name: str = None,
    padding_start_ms: int = 200,
    padding_end_ms: int = 200,
    video_index: int = 0,
    total_videos: int = 1,
    source_language: str = "en",
    target_language: str = "zh",
) -> tuple[list[dict], str]:
    """
    处理单个视频的字幕解析 + AI + 媒体切割，返回 (processed_items, video_stem)

    不包含打包步骤，供 run() 组合使用。
    """
    video_path = Path(video_path)
    subtitle_path = Path(subtitle_path) if subtitle_path else None
    output_dir = Path(output_dir)
    video_stem = video_path.stem

    def progress(step, message, details=None):
        prefix = f"[视频 {video_index + 1}/{total_videos}] " if total_videos > 1 else ""
        full_msg = f"{prefix}{message}"
        print(full_msg)
        if progress_callback:
            progress_callback(step, 5, full_msg, details)

    # Step 0: 检查是否需要转录
    need_transcribe = force_transcribe or (subtitle_path is None or not subtitle_path.exists())

    if need_transcribe:
        progress(0, "Whisper 自动转录...")
        from core.whisper_manager import is_whisper_installed, load_model

        if not is_whisper_installed():
            raise RuntimeError(
                "Whisper 未安装。请运行以下命令安装：\n"
                "pip install faster-whisper"
            )

        from core.whisper_transcribe import save_as_srt

        model = load_model(whisper_model)
        if model is None:
            raise RuntimeError("Whisper 模型加载失败")

        segments_iter, info = model.transcribe(
            str(video_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
        )
        segments = [{"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                     for seg in segments_iter if seg.text.strip()]
        print(f"  转录完成，共 {len(segments)} 段")

        temp_srt = output_dir / f"temp_transcribed_{video_stem}.srt"
        temp_srt.parent.mkdir(parents=True, exist_ok=True)
        save_as_srt(segments, str(temp_srt))
        subtitle_path = temp_srt

    # Step 1: 解析字幕
    progress(1, "解析字幕文件中...")
    subtitles = parse_srt(subtitle_path)

    filtered = filter_short_subtitles(subtitles, min_duration)
    progress(1, f"解析完成：共 {len(subtitles)} 条，保留 {len(filtered)} 条",
             {"total": len(subtitles), "filtered": len(filtered)})
    subtitles = filtered

    if not subtitles:
        raise ValueError(f"视频 {video_stem} 没有符合条件的字幕")

    # Step 2: AI 处理（如有预处理数据则跳过）
    if pre_processed:
        if len(pre_processed) != len(subtitles):
            raise ValueError(f"视频 {video_stem} 预处理数据({len(pre_processed)})与字幕({len(subtitles)})数量不一致")
        processed = []
        for sub, pp in zip(subtitles, pre_processed):
            processed.append({
                "index": sub.index,
                "start_sec": sub.start_sec,
                "end_sec": sub.end_sec,
                "text": pp.get("text") or sub.text,
                "translation": pp.get("translation", ""),
                "notes": pp.get("notes", ""),
                "reason": pp.get("reason", ""),
                "word": pp.get("word", ""),
                "definition": pp.get("definition", "")
            })
        progress(2, f"使用 AI 推荐结果，共 {len(processed)} 条")
    else:
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            progress(2, f"AI 注释 {len(subtitles)} 条字幕中...")
            processed = process_subtitles_with_ai(subtitles, api_key, api_base, model_name, source_language, target_language)

            if not processed:
                raise ValueError(f"视频 {video_stem} AI 处理后没有保留的字幕")
            progress(2, f"AI 处理完成，保留 {len(processed)} 条有价值内容",
                     {"retained": len(processed)})
        else:
            processed = []
            for sub in subtitles:
                processed.append({
                    "index": sub.index,
                    "start_sec": sub.start_sec,
                    "end_sec": sub.end_sec,
                    "text": sub.text,
                    "translation": "",
                    "notes": "",
                    "reason": ""
                })
            progress(2, f"跳过 AI 注释（未配置 API Key），共 {len(processed)} 条")

    # 应用 index 偏移
    processed = _apply_index_offset(processed, index_offset)

    # Step 3: 媒体处理
    progress(3, f"切割音频和截图中 ({len(processed)} 个片段)...")
    media_items = process_media_items(
        str(video_path),
        processed,
        str(output_dir),
        num_workers=num_workers,
        padding_start_ms=padding_start_ms,
        padding_end_ms=padding_end_ms
    )

    # 合并数据（按索引匹配）
    media_map = {m.index: m for m in media_items}
    for p in processed:
        m = media_map.get(p["index"])
        if m:
            p["audio_path"] = m.audio_path
            p["screenshot_path"] = m.screenshot_path
        else:
            p["audio_path"] = ""
            p["screenshot_path"] = ""

    progress(3, f"媒体处理完成")

    # 清理完整音轨缓存，避免下一个视频误用此视频的音频
    full_audio = output_dir / "audio" / "_full.mp3"
    if full_audio.exists():
        full_audio.unlink()

    return processed, video_stem


def run(
    video_paths,            # str | list[str]
    subtitle_paths = None,  # str | list[str] | None，与 video_paths 对应
    output_dir: str = "./output",
    merge: bool = True,     # True=合并到一个牌组, False=每个视频独立牌组
    api_key: str = None,
    min_duration: float = 1.0,
    num_workers: int = 8,
    whisper_model: str = "base",
    language: str = None,
    force_transcribe: bool = False,
    progress_callback=None,
    pre_processed = None,   # 单视频: list[dict]; 多视频: list[list[dict]]
    api_base: str = None,
    model_name: str = None,
    padding_start_ms: int = 200,
    padding_end_ms: int = 200,
    card_styles: list = None,
    theme: str = "default",
    source_language: str = "en",
    target_language: str = "zh",
) -> dict:
    """
    运行完整流程

    Args:
        video_paths: 视频文件路径（单个字符串或列表）
        subtitle_paths: 字幕文件路径（单个字符串、列表或 None，不提供则自动转录）
        output_dir: 输出目录
        merge: 多视频时 True=合并为一个牌组, False=每个视频独立牌组
        api_key: AI API Key
        min_duration: 最短字幕时长（秒）
        num_workers: 并行处理数
        whisper_model: Whisper 模型 (tiny, base, small, medium, large)
        language: 视频语言代码，None 则自动检测
        force_transcribe: 强制使用 Whisper 转录
        progress_callback: 进度回调 callback(step, total_steps, message, details)
        pre_processed: 前端已预处理的注释数据
        api_base: AI API 地址
        model_name: AI 模型名称
        padding_start_ms: 音频前置 Padding（毫秒）
        padding_end_ms: 音频后置 Padding（毫秒）
        card_styles: 卡片风格列表
        theme: 卡片主题

    Returns:
        merge=True:  {"apkg_path": str, "cards_count": int, "processed": list[dict]}
        merge=False: {"results": list[dict], "apkg_paths": list[str], "total_cards": int}
    """
    # ── 参数规范化 ──
    if isinstance(video_paths, str):
        video_paths = [video_paths]

    if subtitle_paths is None:
        subtitle_paths = [None]
    elif isinstance(subtitle_paths, str):
        subtitle_paths = [subtitle_paths]

    # 补齐 subtitle_paths 长度
    while len(subtitle_paths) < len(video_paths):
        subtitle_paths.append(None)

    total_videos = len(video_paths)
    output_dir = Path(output_dir)

    # pre_processed 规范化：单视频用 [pre_processed]，多视频直接使用
    if pre_processed and not isinstance(pre_processed[0], list):
        # 单视频的扁平列表 → 转为嵌套列表
        pre_processed = [pre_processed]

    # ── 公共参数 ──
    common_kwargs = dict(
        api_key=api_key,
        min_duration=min_duration,
        num_workers=num_workers,
        whisper_model=whisper_model,
        language=language,
        force_transcribe=force_transcribe,
        progress_callback=progress_callback,
        api_base=api_base,
        model_name=model_name,
        padding_start_ms=padding_start_ms,
        padding_end_ms=padding_end_ms,
        source_language=source_language,
        target_language=target_language,
    )

    print("=" * 50)
    print(f"ClipLingo - 共 {total_videos} 个视频{' (合并模式)' if merge else ' (独立模式)'}")
    print("=" * 50)

    # ── 清理旧媒体文件 ──
    import shutil
    audio_dir = output_dir / "audio"
    screenshot_dir = output_dir / "screenshots"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
        print(f"已清理旧音频目录: {audio_dir}")
    if screenshot_dir.exists():
        shutil.rmtree(screenshot_dir)
        print(f"已清理旧截图目录: {screenshot_dir}")

    # ── 处理每个视频的 Step 0-3 ──
    all_processed = []  # 合并模式收集所有视频的卡片
    results = []        # 独立模式收集每个视频的结果

    for i, (vp, sp) in enumerate(zip(video_paths, subtitle_paths)):
        index_offset = i * 10000

        # 获取该视频的预处理数据
        video_pre_processed = None
        if pre_processed and i < len(pre_processed):
            video_pre_processed = pre_processed[i]

        processed, video_stem = _process_video_to_media(
            video_path=vp if isinstance(vp, str) else str(vp),
            subtitle_path=sp if isinstance(sp, str) or sp is None else str(sp),
            output_dir=str(output_dir),
            index_offset=index_offset,
            video_index=i,
            total_videos=total_videos if not merge else total_videos,
            pre_processed=video_pre_processed,
            **common_kwargs,
        )

        if merge:
            all_processed.extend(processed)
        else:
            # 独立模式：每个视频立即打包
            _progress = common_kwargs.get("progress_callback")
            step4_msg = f"[视频 {i + 1}/{total_videos}] 打包 Anki 牌组中 ({len(processed)} 张卡片)..."
            print(step4_msg)
            if _progress:
                _progress(4, 5, step4_msg)

            apkg_path = create_apkg(
                video_stem,
                processed,
                str(output_dir),
                str(audio_dir),
                str(screenshot_dir),
                card_styles=card_styles,
                theme=theme
            )

            results.append({
                "video_name": video_stem,
                "apkg_path": str(apkg_path),
                "cards_count": len(processed),
                "processed": processed,
            })

            done_msg = f"[视频 {i + 1}/{total_videos}] 完成! {len(processed)} 张卡片"
            print(done_msg)
            if _progress:
                _progress(5, 5, done_msg)

    # ── Step 4: 打包（合并模式） ──
    if merge:
        if not all_processed:
            raise ValueError("没有生成任何卡片")

        progress_callback_obj = common_kwargs.get("progress_callback")
        pack_msg = f"打包 Anki 牌组中 ({len(all_processed)} 张卡片)..."
        print(pack_msg)
        if progress_callback_obj:
            progress_callback_obj(4, 5, pack_msg)

        # 用第一个视频名 + 数量作为牌组名
        first_stem = Path(video_paths[0]).stem
        if total_videos > 1:
            deck_name = f"{first_stem}_等{total_videos}个"
        else:
            deck_name = first_stem

        apkg_path = create_apkg(
            deck_name,
            all_processed,
            str(output_dir),
            str(audio_dir),
            str(screenshot_dir),
            card_styles=card_styles,
            theme=theme
        )

        print(f"\n[5/5] 完成!")
        print(f"牌组文件: {apkg_path}")
        print(f"卡片数量: {len(all_processed)}")

        return {
            "apkg_path": str(apkg_path),
            "cards_count": len(all_processed),
            "processed": all_processed
        }
    else:
        total_cards = sum(r["cards_count"] for r in results)
        print(f"\n全部完成! 共 {total_videos} 个视频, {total_cards} 张卡片")
        return {
            "results": results,
            "apkg_paths": [r["apkg_path"] for r in results],
            "total_cards": total_cards,
        }


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="ClipLingo")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("subtitle", nargs="?", default=None, help="字幕文件路径（不提供则自动用 Whisper 转录）")
    parser.add_argument("output", nargs="?", default="./output", help="输出目录")
    parser.add_argument("--model", "-m", default="base", choices=["tiny", "base", "small", "medium", "large"],
                        help="Whisper 模型大小 (默认: base)")
    parser.add_argument("--language", "-l", default=None, help="视频语言代码，如 en, zh")
    parser.add_argument("--force-transcribe", "-t", action="store_true",
                        help="强制使用 Whisper 转录，忽略已有字幕")

    args = parser.parse_args()

    try:
        run(
            args.video,
            args.subtitle,
            args.output,
            whisper_model=args.model,
            language=args.language,
            force_transcribe=args.force_transcribe
        )
    except Exception as e:
        print(f"\n错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
