"""
ChunkedASR — 长音频分片转录装饰器
将长音频切割为重叠块，并发转录后合并结果
使用 ffmpeg/ffprobe，不依赖 pydub（兼容 Python 3.13+）
"""
import logging
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from .base import BaseASREngine
from core.media_cut import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)

_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

MS_PER_SECOND = 1000
DEFAULT_CHUNK_LENGTH_SEC = 60 * 10   # 10 分钟
DEFAULT_CHUNK_OVERLAP_SEC = 10       # 10 秒重叠
DEFAULT_CHUNK_CONCURRENCY = 3        # 3 并发


def _get_audio_duration_sec(audio_path: str) -> float:
    """用 ffprobe 获取音频时长（秒）"""
    try:
        result = subprocess.run([
            get_ffprobe_path(), "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        ], check=True, capture_output=True, text=True, **_NO_WINDOW)
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"获取音频时长失败: {e}")
        return 0.0


class ChunkedASR:
    """长音频分片转录器

    为任何 BaseASREngine 实例添加长音频分片能力。
    短于 chunk_length 的音频直接转录，不做分片。
    """

    def __init__(
        self,
        engine: BaseASREngine,
        chunk_length: int = DEFAULT_CHUNK_LENGTH_SEC,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_SEC,
        chunk_concurrency: int = DEFAULT_CHUNK_CONCURRENCY,
    ):
        self.engine = engine
        self.chunk_length_sec = chunk_length
        self.chunk_overlap_sec = chunk_overlap
        self.chunk_concurrency = chunk_concurrency

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[dict]:
        # 获取时长
        total_duration_sec = _get_audio_duration_sec(audio_path)
        if total_duration_sec <= 0:
            return self.engine.transcribe(audio_path, language, progress_callback)

        # 短音频直接转录
        if total_duration_sec <= self.chunk_length_sec:
            logger.debug("音频短于分片阈值，直接转录")
            return self.engine.transcribe(audio_path, language, progress_callback)

        # 计算分片时间点
        chunks = self._plan_chunks(total_duration_sec)
        logger.info(f"长音频分片完成，共 {len(chunks)} 个片段")

        if progress_callback:
            progress_callback(0.0, f"音频分片为 {len(chunks)} 段，开始并行转录...")

        # 用 ffmpeg 切割 + 并发转录
        results = self._transcribe_chunks(audio_path, chunks, language, progress_callback)

        # 合并结果
        merged = self._merge_results(results, chunks)

        if progress_callback:
            progress_callback(1.0, f"分片转录完成，共 {len(merged)} 段")

        return merged

    def _plan_chunks(self, total_duration_sec: float) -> list[tuple[float, float, int]]:
        """规划分片时间点，返回 [(start_sec, end_sec, offset_ms), ...]"""
        chunks = []
        start_sec = 0.0

        while start_sec < total_duration_sec:
            end_sec = min(start_sec + self.chunk_length_sec, total_duration_sec)
            chunks.append((start_sec, end_sec, int(start_sec * MS_PER_SECOND)))

            if end_sec >= total_duration_sec:
                break
            start_sec += self.chunk_length_sec - self.chunk_overlap_sec

        return chunks

    def _transcribe_chunks(
        self,
        audio_path: str,
        chunks: list[tuple[float, float, int]],
        language: Optional[str],
        progress_callback: Optional[Callable[[float, str], None]],
    ) -> list[Optional[list[dict]]]:
        """并发转录所有分片"""
        results: list[Optional[list[dict]]] = [None] * len(chunks)
        total = len(chunks)

        def transcribe_one(idx: int, start_sec: float, end_sec: float) -> tuple[int, Optional[list[dict]]]:
            """用 ffmpeg 切出一个分片，写入临时文件，调用引擎转录"""
            tmp_path = None
            try:
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp3")
                os.close(tmp_fd)
                duration = end_sec - start_sec
                subprocess.run([
                    get_ffmpeg_path(), "-y", "-ss", str(start_sec), "-i", audio_path,
                    "-t", str(duration), "-vn", "-acodec", "libmp3lame", "-q:a", "7",
                    tmp_path,
                ], check=True, capture_output=True, text=True, **_NO_WINDOW)

                segments = self.engine.transcribe(tmp_path, language)
                logger.debug(f"分片 {idx + 1}/{total} 转录完成，{len(segments) if segments else 0} 段")
                return idx, segments
            except Exception as e:
                logger.error(f"分片 {idx + 1}/{total} 转录失败: {e}")
                return idx, None
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        completed = 0
        with ThreadPoolExecutor(max_workers=self.chunk_concurrency) as executor:
            futures = {
                executor.submit(transcribe_one, i, start_sec, end_sec): i
                for i, (start_sec, end_sec, _) in enumerate(chunks)
            }
            for future in as_completed(futures):
                idx, segments = future.result()
                results[idx] = segments
                completed += 1
                if progress_callback:
                    progress_callback(
                        completed / total * 0.95,
                        f"转录分片 {completed}/{total}...",
                    )

        return results

    def _merge_results(
        self,
        chunk_results: list[Optional[list[dict]]],
        chunks: list[tuple[float, float, int]],
    ) -> list[dict]:
        """合并分片结果：偏移时间戳，去掉重叠区域的重复段

        策略：只取每个分片前 chunk_length - chunk_overlap 秒的内容，
        最后一块取全部。
        """
        valid_chunk_sec = self.chunk_length_sec - self.chunk_overlap_sec

        all_segments = []
        for i, (segments, (_, _, offset_ms)) in enumerate(zip(chunk_results, chunks)):
            if segments is None:
                continue

            offset_sec = offset_ms / 1000.0
            max_local_sec = valid_chunk_sec if i < len(chunks) - 1 else float("inf")

            for seg in segments:
                seg_start = seg["start"] + offset_sec
                # 跳过重叠区域的段（最后一块除外）
                if i < len(chunks) - 1 and seg["start"] >= max_local_sec:
                    continue
                all_segments.append({
                    "start": seg_start,
                    "end": seg["end"] + offset_sec,
                    "text": seg["text"],
                })

        # 按 start 排序
        all_segments.sort(key=lambda s: s["start"])

        # 去重：合并时间重叠且文本相同的段
        deduped = []
        for seg in all_segments:
            if deduped and seg["text"] == deduped[-1]["text"]:
                deduped[-1]["end"] = max(deduped[-1]["end"], seg["end"])
            else:
                deduped.append(seg)

        return deduped
