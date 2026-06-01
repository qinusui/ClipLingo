"""
媒体切割模块 - 使用 ffmpeg 切割音频和截取视频截图
"""

import subprocess
import sys
import os
import logging

# Windows 下防止子进程弹出终端窗口
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass

# 确保项目根目录在 sys.path 中（支持从 backend 导入时使用）
_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from errors import ClipLingoError, ErrorCode

logger = logging.getLogger(__name__)

@dataclass
class MediaItem:
    """媒体条目"""
    index: int
    start_sec: float
    end_sec: float
    audio_path: str
    screenshot_path: str


PADDING_DEFAULT_MS = 200  # 默认 padding 毫秒数


def _get_bin_path(tool_name: str) -> str:
    """获取 ffmpeg/ffprobe 的路径，兼容打包和开发环境"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的路径查找
        possible_paths = [
            Path(sys._MEIPASS) / "bin" / tool_name,  # _internal/bin/
            Path(sys.executable).parent / "bin" / tool_name,  # exe 同级 bin/
            Path(sys.executable).parent / tool_name,  # exe 同级
            Path(sys._MEIPASS) / tool_name,  # _internal/
        ]
        for path in possible_paths:
            if path.exists():
                logger.info(f"Found {tool_name} at: {path}")
                return str(path)
        logger.warning(f"{tool_name} not found in any expected location")
    # 开发环境或 Docker - 直接使用命令名
    return tool_name


def get_ffmpeg_path() -> str:
    """获取 ffmpeg 路径"""
    return _get_bin_path("ffmpeg.exe" if os.name == 'nt' else "ffmpeg")


def get_ffprobe_path() -> str:
    """获取 ffprobe 路径"""
    return _get_bin_path("ffprobe.exe" if os.name == 'nt' else "ffprobe")


def get_video_duration(video_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒）"""
    cmd = [
        get_ffprobe_path(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=10, **_NO_WINDOW)
    except FileNotFoundError:
        raise ClipLingoError(ErrorCode.FFMPEG_NOT_FOUND, "ffprobe 未找到")
    except subprocess.TimeoutExpired:
        raise ClipLingoError(ErrorCode.FFMPEG_FAILED, "ffprobe 获取视频时长超时")

    if result.returncode != 0:
        raise ClipLingoError(ErrorCode.FFMPEG_FAILED, f"ffprobe 失败: {result.stderr[:200]}")

    try:
        return float(result.stdout.strip())
    except ValueError:
        raise ClipLingoError(ErrorCode.FFMPEG_FAILED, f"无法解析视频时长: {result.stdout[:100]}")


def apply_padding(items: list[dict], video_duration: float,
                   padding_start_ms: int = 200, padding_end_ms: int = 200) -> list[dict]:
    """
    为每条字幕的音频切割添加头尾 Padding，避免开头结尾太突兀。
    保持原始 start_sec/end_sec 不变（用于卡片显示），
    新增 cut_start/cut_end 表示实际切割范围。
    """
    pad_start_s = padding_start_ms / 1000.0
    pad_end_s   = padding_end_ms / 1000.0

    for i, item in enumerate(items):
        start = item["start_sec"]
        end = item["end_sec"]

        pad_start = start - pad_start_s
        pad_end   = end   + pad_end_s

        # 不超出视频边界
        pad_start = max(0.0, pad_start)
        pad_end   = min(video_duration, pad_end)

        # 不侵入前一句
        if i > 0:
            prev_end = items[i - 1]["end_sec"]
            pad_start = max(pad_start, prev_end)

        # 不侵入后一句
        if i < len(items) - 1:
            next_start = items[i + 1]["start_sec"]
            pad_end = min(pad_end, next_start)

        item["cut_start"] = pad_start
        item["cut_end"]   = pad_end
        # 截图取原始时间中点
        item["snapshot_time"] = (start + end) / 2

    return items


def extract_full_audio(video_path: str, output_path: str, quality: int = 2) -> tuple[bool, str]:
    """从视频提取完整音轨（MP3），仅解码一次视频。返回 (成功, 错误信息)"""
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", video_path,
        "-vn", "-acodec", "libmp3lame",
        "-q:a", str(quality), "-ar", "44100",
        output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True,
                                encoding='utf-8', errors='replace', timeout=600, **_NO_WINDOW)
        if result.returncode == 0:
            return True, ""
        return False, result.stderr[:300] if result.stderr else "ffmpeg 返回非零退出码"
    except FileNotFoundError:
        raise ClipLingoError(ErrorCode.FFMPEG_NOT_FOUND, "ffmpeg 未找到")
    except subprocess.TimeoutExpired:
        return False, "提取音轨超时"


def cut_audio(
    source_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    quality: int = 2
) -> bool:
    """
    从音/视频文件切割片段（-ss 在 -i 前，输入seek，速度快）

    Args:
        source_path: 音频或视频文件路径
        start_sec: 开始时间（秒）
        end_sec: 结束时间（秒）
        output_path: 输出路径
        quality: 音频质量 (0-9, 越小越好)
    """
    duration = end_sec - start_sec
    cmd = [
        get_ffmpeg_path(), "-y",
        "-ss", f"{start_sec:.3f}", "-t", f"{duration:.3f}",
        "-i", source_path,
        "-vn", "-acodec", "libmp3lame",
        "-q:a", str(quality), "-ar", "44100",
        output_path
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True,
            encoding='utf-8', errors='replace',
            timeout=max(30, duration * 2), **_NO_WINDOW
        )
        return result.returncode == 0
    except FileNotFoundError:
        raise ClipLingoError(ErrorCode.FFMPEG_NOT_FOUND, "ffmpeg 未找到")
    except subprocess.TimeoutExpired:
        return False


def capture_screenshot(
    video_path: str,
    timestamp: float,
    output_path: str,
    quality: int = 2
) -> bool:
    """
    截取视频中间帧

    Args:
        video_path: 视频文件路径
        timestamp: 时间戳（秒）
        output_path: 输出路径
        quality: 图像质量 (1-31, 越小越好)

    Returns:
        是否成功
    """
    cmd = [
        get_ffmpeg_path(),
        "-y", "-nostdin",
        "-ss", f"{timestamp:.3f}",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", str(quality),
        "-threads", "1",
        output_path
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding='utf-8', errors='replace',
            timeout=30,
            **_NO_WINDOW
        )
        return result.returncode == 0
    except FileNotFoundError:
        raise ClipLingoError(ErrorCode.FFMPEG_NOT_FOUND, "ffmpeg 未找到")
    except subprocess.TimeoutExpired:
        return False


def process_media_items(
    video_path: str,
    items: list[dict],
    output_dir: str,
    num_workers: int = 8,
    padding_start_ms: int = 200,
    padding_end_ms: int = 200
) -> list[MediaItem]:
    """
    批量处理媒体条目

    Args:
        video_path: 视频文件路径
        items: 字幕数据列表，每项包含 start_sec, end_sec
        output_dir: 输出目录
        num_workers: 并行数
        padding_start_ms: 开头提前毫秒数（100-1000，整百）
        padding_end_ms: 结尾延后毫秒数（100-1000，整百）
    """
    output_path = Path(output_dir)
    audio_dir = output_path / "audio"
    screenshot_dir = output_path / "screenshots"

    audio_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # 获取视频时长并计算 padding
    video_duration = get_video_duration(video_path)
    items = apply_padding(items, video_duration, padding_start_ms, padding_end_ms)

    # 过滤掉超出视频时长的条目（字幕时间戳可能超出视频范围）
    original_count = len(items)
    items = [item for item in items if item.get('snapshot_time', 0) < video_duration]
    if len(items) < original_count:
        skipped = original_count - len(items)
        print(f"跳过 {skipped} 条超出视频时长的字幕（视频时长: {video_duration:.2f}s）")

    # Step 1: 提取完整音轨（视频只解码一次）
    full_audio_path = str(audio_dir / "_full.mp3")
    if Path(full_audio_path).exists() and Path(full_audio_path).stat().st_size > 0:
        print(f"完整音轨已存在，跳过提取")
    else:
        print(f"提取完整音轨...")
        ok, err_msg = extract_full_audio(video_path, full_audio_path)
        if not ok:
            raise ClipLingoError(ErrorCode.FFMPEG_FAILED, f"提取音轨失败: {err_msg}")

    # Step 2: 并行逐条截图（-ss 在 -i 前，输入跳转快）
    print(f"截图 {len(items)} 帧，{num_workers} 并发...")
    ss_map = {}

    def _ss_single(item):
        idx = item["index"]
        path = str(screenshot_dir / f"card_{idx:04d}.jpg")
        if Path(path).exists() and Path(path).stat().st_size > 0:
            return (idx, path)
        ok = capture_screenshot(video_path, item["snapshot_time"], path)
        return (idx, path) if ok else (idx, "")

    with ThreadPoolExecutor(max_workers=num_workers) as ss_executor:
        for idx, path in ss_executor.map(_ss_single, items):
            if path:
                ss_map[idx] = path
    print(f"截图完成: {len(ss_map)}/{len(items)}")

    # Step 3: 并行切音频
    print(f"开始音频切片，{len(items)} 条，{num_workers} 并发...")
    results = []

    def process_single(item: dict) -> MediaItem | None:
        idx = item.get("index", 0)
        cut_start = item["cut_start"]
        cut_end = item["cut_end"]

        audio_path = str(audio_dir / f"card_{idx:04d}.mp3")
        screenshot_path = ss_map.get(idx, "")

        # 如果音频文件已存在且非空，跳过切割
        if Path(audio_path).exists() and Path(audio_path).stat().st_size > 0:
            return MediaItem(
                index=idx,
                start_sec=item["start_sec"],
                end_sec=item["end_sec"],
                audio_path=audio_path,
                screenshot_path=screenshot_path
            )

        if cut_audio(full_audio_path, cut_start, cut_end, audio_path):
            return MediaItem(
                index=idx,
                start_sec=item["start_sec"],
                end_sec=item["end_sec"],
                audio_path=audio_path,
                screenshot_path=screenshot_path
            )
        logger.warning(f"音频切割失败: card_{idx:04d} ({cut_start:.2f}s - {cut_end:.2f}s)")
        return MediaItem(
            index=idx,
            start_sec=item["start_sec"],
            end_sec=item["end_sec"],
            audio_path="",
            screenshot_path=screenshot_path
        )

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(process_single, item): item for item in items}

        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                results.append(result)

            if i % 10 == 0 or i == len(items):
                print(f"  进度: {i}/{len(items)}")

    results.sort(key=lambda x: x.index)
    print(f"媒体处理完成，{len(results)} 条成功")

    return results


if __name__ == '__main__':
    # 测试
    import sys
    if len(sys.argv) > 1:
        video = sys.argv[1]
        print(f"测试截图: {capture_screenshot(video, 10.0, 'test.jpg')}")