"""
ClipLingo - 主程序
将视频和字幕文件转换为可导入 Anki 的牌组
"""

import os
import sys
import io

# ── 最早阶段：强制 UTF-8 模式（解决中文路径问题） ──
if sys.platform == "win32":
    if not os.environ.get("PYTHONIOENCODING"):
        os.environ["PYTHONIOENCODING"] = "utf-8"
    if not os.environ.get("PYTHONUTF8"):
        os.environ["PYTHONUTF8"] = "1"
    for _name in ("stdout", "stderr", "stdin"):
        _stream = getattr(sys, _name, None)
        if _stream is not None and hasattr(_stream, "buffer") and _stream.buffer is not None:
            try:
                setattr(sys, _name, io.TextIOWrapper(
                    _stream.buffer, encoding="utf-8", errors="replace"
                ))
            except Exception:
                pass

import json
from pathlib import Path

# 处理 --version 参数（在导入模块之前，避免依赖问题）
if "--version" in sys.argv:
    print("ClipLingo 1.3.1")
    sys.exit(0)

from core.parse_srt import parse_srt, filter_short_subtitles, Subtitle
from core.ai_process import process_subtitles_with_ai
from core.media_cut import process_media_items
from core.pack_apkg import create_apkg


def run(
    video_path: str,
    subtitle_path: str = None,
    output_dir: str = "./output",
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
    card_styles: list = None,
    theme: str = "default"
) -> dict:
    """
    运行完整流程

    Args:
        video_path: 视频文件路径
        subtitle_path: 字幕文件路径（可选，不提供则自动转录）
        output_dir: 输出目录
        api_key: DeepSeek API Key
        min_duration: 最短字幕时长（秒）
        num_workers: 并行处理数
        whisper_model: Whisper 模型 (tiny, base, small, medium, large)
        language: 视频语言代码，None 则自动检测
        force_transcribe: 强制使用 Whisper 转录（忽略已有字幕文件）
        progress_callback: 进度回调 callback(step, total_steps, message, details)
        pre_processed: 前端已通过 AI 推荐预处理的注释数据，提供后跳过 AI 步骤

    Returns:
        dict: 包含 apkg_path, cards_count, processed 等信息
    """
    video_path = Path(video_path)
    subtitle_path = Path(subtitle_path) if subtitle_path else None
    output_dir = Path(output_dir)

    TOTAL_STEPS = 5

    def progress(step, message, details=None):
        print(message)
        if progress_callback:
            progress_callback(step, TOTAL_STEPS, message, details)

    print("=" * 50)
    print("ClipLingo")
    print("=" * 50)

    # 检查是否有 checkpoint 可以恢复
    checkpoint_path = output_dir / "checkpoint.json"
    resume_from_checkpoint = False

    if checkpoint_path.exists() and not pre_processed:
        try:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            # 验证 checkpoint 与当前输入匹配（文件路径 + 所有影响输出的参数）
            cp = checkpoint.get("params", {})
            params_match = (
                checkpoint.get("video_path") == str(video_path) and
                checkpoint.get("subtitle_path") == str(subtitle_path) and
                cp.get("min_duration") == min_duration and
                cp.get("padding_start_ms") == padding_start_ms and
                cp.get("padding_end_ms") == padding_end_ms and
                cp.get("model_name") == model_name and
                cp.get("api_base") == api_base and
                cp.get("language") == language and
                cp.get("card_styles") == card_styles and
                cp.get("theme") == theme
            )
            if params_match:
                print(f"发现 checkpoint，从 Step 3 恢复...")
                processed = checkpoint["processed"]
                resume_from_checkpoint = True
                # 跳转到 Step 3
                progress(3, f"切割音频和截图中 ({len(processed)} 个片段)...")
                media_items = process_media_items(
                    str(video_path),
                    processed,
                    str(output_dir),
                    num_workers=num_workers,
                    padding_start_ms=padding_start_ms,
                    padding_end_ms=padding_end_ms
                )
                # 合并数据
                for p, m in zip(processed, media_items):
                    p["audio_path"] = m.audio_path
                    p["screenshot_path"] = m.screenshot_path
                progress(3, f"媒体处理完成")
                # Step 4: 打包
                progress(4, f"打包 Anki 牌组中 ({len(processed)} 张卡片)...")
                audio_dir = output_dir / "audio"
                screenshot_dir = output_dir / "screenshots"
                apkg_path = create_apkg(
                    video_path.stem,
                    processed,
                    str(output_dir),
                    str(audio_dir),
                    str(screenshot_dir),
                    card_styles=card_styles,
                    theme=theme
                )
                # 完成
                print("\n[5/5] 完成!")
                print(f"牌组文件: {apkg_path}")
                print(f"卡片数量: {len(processed)}")
                return {
                    "apkg_path": str(apkg_path),
                    "cards_count": len(processed),
                    "processed": processed
                }
        except Exception as e:
            print(f"Checkpoint 加载失败，从头开始: {e}")

    # 如果不是从 checkpoint 恢复，清理旧的媒体文件
    if not resume_from_checkpoint:
        import shutil
        audio_dir = output_dir / "audio"
        screenshot_dir = output_dir / "screenshots"
        if audio_dir.exists():
            shutil.rmtree(audio_dir)
            print(f"已清理旧音频目录: {audio_dir}")
        if screenshot_dir.exists():
            shutil.rmtree(screenshot_dir)
            print(f"已清理旧截图目录: {screenshot_dir}")

    # Step 0: 检查是否需要转录
    need_transcribe = force_transcribe or (subtitle_path is None or not subtitle_path.exists())

    if need_transcribe:
        print("[0/5] Whisper 自动转录...")
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

        # 保存为 SRT 供后续使用
        temp_srt = output_dir / "temp_transcribed.srt"
        temp_srt.parent.mkdir(parents=True, exist_ok=True)
        save_as_srt(segments, str(temp_srt))
        subtitle_path = temp_srt

    # Step 1: 解析字幕
    progress(1, "解析字幕文件中...")
    subtitles = parse_srt(subtitle_path)

    # 过滤过短字幕
    filtered = filter_short_subtitles(subtitles, min_duration)
    progress(1, f"解析完成：共 {len(subtitles)} 条，保留 {len(filtered)} 条",
             {"total": len(subtitles), "filtered": len(filtered)})
    subtitles = filtered

    if not subtitles:
        raise ValueError("没有符合条件的字幕")

    # Step 2: AI 处理（如有预处理数据则跳过）
    if pre_processed:
        # pre_processed 与 subtitles 来自同一批选中的句子，按位置顺序匹配
        if len(pre_processed) != len(subtitles):
            raise ValueError(f"预处理数据({len(pre_processed)})与字幕({len(subtitles)})数量不一致")
        processed = []
        for sub, pp in zip(subtitles, pre_processed):
            processed.append({
                "index": sub.index,
                "start_sec": sub.start_sec,
                "end_sec": sub.end_sec,
                "text": sub.text,
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
            processed = process_subtitles_with_ai(subtitles, api_key, api_base, model_name)

            if not processed:
                raise ValueError("AI 处理后没有保留的字幕")
            progress(2, f"AI 处理完成，保留 {len(processed)} 条有价值内容",
                     {"retained": len(processed)})
        else:
            # 无 API Key 时跳过 AI，使用空翻译/注释
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

    # 保存 checkpoint（processed 数据 + 所有影响输出的参数）
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_params = {
        "video_path": str(video_path),
        "subtitle_path": str(subtitle_path),
        "processed": processed,
        "params": {
            "min_duration": min_duration,
            "padding_start_ms": padding_start_ms,
            "padding_end_ms": padding_end_ms,
            "model_name": model_name,
            "api_base": api_base,
            "language": language,
            "card_styles": card_styles,
            "theme": theme,
        }
    }
    with open(checkpoint_path, 'w', encoding='utf-8') as f:
        json.dump(checkpoint_params, f, ensure_ascii=False, indent=2)
    print(f"Checkpoint 已保存: {checkpoint_path}")

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

    # 合并数据
    for p, m in zip(processed, media_items):
        p["audio_path"] = m.audio_path
        p["screenshot_path"] = m.screenshot_path

    progress(3, f"媒体处理完成")
    # Step 4: 打包
    progress(4, f"打包 Anki 牌组中 ({len(processed)} 张卡片)...")
    audio_dir = output_dir / "audio"
    screenshot_dir = output_dir / "screenshots"

    apkg_path = create_apkg(
        video_path.stem,
        processed,
        str(output_dir),
        str(audio_dir),
        str(screenshot_dir),
        card_styles=card_styles,
        theme=theme
    )

    # 完成
    print("\n[5/5] 完成!")
    print(f"牌组文件: {apkg_path}")
    print(f"卡片数量: {len(processed)}")

    return {
        "apkg_path": str(apkg_path),
        "cards_count": len(processed),
        "processed": processed
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