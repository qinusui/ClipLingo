"""
BcutASREngine — Bilibili 必剪云端语音识别
使用 Bilibili 公开 API，免费、无需 API Key

Portions adapted from VideoCaptioner (MIT License)
Copyright (c) 2024 weifangma
https://github.com/weifangma/VideoCaptioner
"""
import json
import logging
import os
import sys
import time
import uuid
import zlib
from typing import Callable, Optional

import requests

from .base import BaseASREngine
from . import register_engine
from core.media_cut import get_ffmpeg_path, get_ffprobe_path

_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

logger = logging.getLogger(__name__)

API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE_URL + "/resource/create"
API_COMMIT_UPLOAD = API_BASE_URL + "/resource/create/complete"
API_CREATE_TASK = API_BASE_URL + "/task"
API_QUERY_RESULT = API_BASE_URL + "/task/result"

HEADERS = {
    "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
    "Content-Type": "application/json",
}

# 限流参数
RATE_LIMIT_MAX_CALLS = 100
RATE_LIMIT_MAX_DURATION = 360 * 60       # 360 分钟
RATE_LIMIT_TIME_WINDOW = 12 * 3600       # 12 小时

# 缓存过期时间
CACHE_EXPIRE_SECONDS = 86400 * 2          # 2 天


def _get_cache_dir() -> str:
    """获取缓存目录（frozen 模式用 APPDATA，开发模式用项目目录）"""
    if getattr(sys, 'frozen', False):
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'ClipLingo', 'cache', 'asr')
    else:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cache', 'asr')


class _NoOpCache:
    """占位缓存：diskcache 不可用时，get/set 均为空操作"""
    def get(self, key, default=None): return default
    def set(self, key, value, **kw): pass
    def _sql(self, *args, **kw): return type('_FakeResult', (), {'fetchall': lambda: []})()


def _get_diskcache():
    """延迟导入 diskcache，获取 ASR 专用的缓存实例"""
    try:
        import diskcache
    except ImportError:
        return _NoOpCache()
    cache_dir = _get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    return diskcache.Cache(cache_dir)


@register_engine
class BcutASREngine(BaseASREngine):
    """必剪云端语音识别引擎

    使用 Bilibili 的公开 ASR API，无需 API Key。
    支持音频缓存（CRC32 校验）和限流控制。
    长音频自动由 ChunkedASR 处理。
    """

    ENGINE_ID = "bcut"
    ENGINE_NAME = "Bilibili 必剪（云端）"

    def __init__(self, need_word_time_stamp: bool = False):
        self.need_word_time_stamp = need_word_time_stamp
        self._cache = None

    # 视频扩展名：需要先提取音轨再上传
    _VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".wmv"}

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[dict]:
        # 如果是视频文件，先用 ffmpeg 提取音轨
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in self._VIDEO_EXTENSIONS:
            import subprocess
            import tempfile
            if progress_callback:
                progress_callback(0.0, "提取音频...")
            tmp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp_mp3.close()
            try:
                subprocess.run([
                    get_ffmpeg_path(), "-y", "-i", audio_path,
                    "-vn", "-acodec", "libmp3lame", "-q:a", "7",
                    tmp_mp3.name,
                ], check=True, capture_output=True, text=True, **_NO_WINDOW)
                audio_path = tmp_mp3.name
            except subprocess.CalledProcessError as e:
                os.unlink(tmp_mp3.name)
                raise RuntimeError(f"提取音频失败: {e.stderr}")
            except Exception:
                os.unlink(tmp_mp3.name)
                raise
            self._tmp_audio = tmp_mp3.name
        else:
            self._tmp_audio = None

        try:
            return self._transcribe_audio(audio_path, language, progress_callback)
        finally:
            if self._tmp_audio and os.path.exists(self._tmp_audio):
                os.unlink(self._tmp_audio)

    def _transcribe_audio(
        self,
        audio_path: str,
        language: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> list[dict]:
        # 加载音频
        with open(audio_path, "rb") as f:
            file_binary = f.read()

        # CRC32 作为缓存键
        crc32_value = zlib.crc32(file_binary) & 0xFFFFFFFF
        crc32_hex = format(crc32_value, "08x")
        cache_key = f"BcutASREngine:{crc32_hex}"

        # 检查缓存
        cache = _get_diskcache()
        cached = cache.get(cache_key, default=None)
        if cached is not None:
            logger.info("Bcut ASR 命中缓存，直接返回")
            if progress_callback:
                progress_callback(1.0, "命中缓存，转录完成")
            return cached

        # 获取音频时长（用于限流检查）
        audio_duration = self._get_audio_duration(audio_path)

        if progress_callback:
            progress_callback(0.0, "检查限流...")

        # 限流检查
        self._check_rate_limit(cache, audio_duration)

        # 4 步 API 流程
        if progress_callback:
            progress_callback(0.05, "上传音频...")

        session = requests.Session()
        try:
            # Step 1-2: 上传
            download_url = self._upload(session, file_binary)

            # Step 3: 创建任务
            if progress_callback:
                progress_callback(0.3, "创建识别任务...")
            task_id = self._create_task(session, download_url)

            # Step 4: 轮询结果
            if progress_callback:
                progress_callback(0.4, "等待识别结果...")
            result = self._poll_result(session, task_id, progress_callback)

            if progress_callback:
                progress_callback(0.95, "解析结果...")
        finally:
            session.close()

        # 解析为统一格式
        segments = self._parse_result(result)

        # 限流记录
        self._record_rate_limit(cache, audio_duration)

        # 写入缓存
        cache.set(cache_key, segments, expire=CACHE_EXPIRE_SECONDS)

        if progress_callback:
            progress_callback(1.0, f"识别完成，共 {len(segments)} 段")

        return segments

    @classmethod
    def is_available(cls) -> bool:
        return True  # 纯 HTTP API，无需特殊依赖

    # ── 内部方法 ──

    def _get_audio_duration(self, audio_path: str) -> float:
        """用 ffprobe 获取音频时长（秒）"""
        try:
            import subprocess
            result = subprocess.run([
                get_ffprobe_path(), "-v", "quiet", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
            ], check=True, capture_output=True, text=True, **_NO_WINDOW)
            return float(result.stdout.strip())
        except Exception:
            return 60.0  # 默认估值为 60 秒

    def _upload(self, session: requests.Session, file_binary: bytes) -> str:
        """上传音频文件，返回 download_url"""
        # Step 1: 请求上传授权
        payload = json.dumps({
            "type": 2,
            "name": "audio.mp3",
            "size": len(file_binary),
            "ResourceFileType": "mp3",
            "model_id": "8",
        })
        resp = session.post(API_REQ_UPLOAD, data=payload, headers=HEADERS)
        resp.raise_for_status()
        body = resp.json()
        resp_data = body.get("data")
        if resp_data is None:
            raise RuntimeError(f"Bcut ASR 上传授权失败: {body}")

        upload_urls = resp_data["upload_urls"]
        per_size = resp_data["per_size"]
        in_boss_key = resp_data["in_boss_key"]
        resource_id = resp_data["resource_id"]
        upload_id = resp_data["upload_id"]

        # Step 2: 分片上传
        etags = []
        for clip in range(len(upload_urls)):
            start_range = clip * per_size
            end_range = (clip + 1) * per_size
            resp = session.put(
                upload_urls[clip],
                data=file_binary[start_range:end_range],
                headers=HEADERS,
            )
            resp.raise_for_status()
            etag = resp.headers.get("Etag")
            if etag:
                etags.append(etag)

        # Step 3: 提交上传
        commit_data = json.dumps({
            "InBossKey": in_boss_key,
            "ResourceId": resource_id,
            "Etags": ",".join(etags),
            "UploadId": upload_id,
            "model_id": "8",
        })
        resp = session.post(API_COMMIT_UPLOAD, data=commit_data, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()["data"]["download_url"]

    def _create_task(self, session: requests.Session, download_url: str) -> str:
        """创建 ASR 任务，返回 task_id"""
        resp = session.post(
            API_CREATE_TASK,
            json={"resource": download_url, "model_id": "8"},
            headers=HEADERS,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data")
        if data is None:
            raise RuntimeError(f"Bcut ASR 创建任务失败: {body}")
        return data["task_id"]

    def _poll_result(
        self,
        session: requests.Session,
        task_id: str,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> dict:
        """轮询任务结果（最多 500 次，每次 1 秒）"""
        for i in range(500):
            resp = session.get(
                API_QUERY_RESULT,
                params={"model_id": 7, "task_id": task_id},
                headers=HEADERS,
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data")
            if data is None:
                # API 返回异常（可能任务不存在、已过期、服务端限流等）
                msg = body.get("msg", "") or body.get("message", "")
                raise RuntimeError(
                    f"Bcut ASR 查询结果失败: {msg or body}"
                )

            if data["state"] == 4:  # 完成
                return json.loads(data["result"])

            if progress_callback and i % 5 == 0:
                progress_callback(0.4 + 0.55 * (i / 500), f"识别中... ({i}s)")

            time.sleep(1)

        raise RuntimeError("Bcut ASR 任务超时（500 秒）")

    def _parse_result(self, resp_data: dict) -> list[dict]:
        """解析 API 返回的 utterances 为统一格式"""
        segments = []
        if self.need_word_time_stamp:
            for u in resp_data.get("utterances", []):
                for w in u.get("words", []):
                    text = w["label"].strip()
                    if text:
                        segments.append({
                            "start": w["start_time"] / 1000.0,
                            "end": w["end_time"] / 1000.0,
                            "text": text,
                        })
        else:
            for u in resp_data.get("utterances", []):
                text = u.get("transcript", "").strip()
                if text:
                    segments.append({
                        "start": u["start_time"] / 1000.0,
                        "end": u["end_time"] / 1000.0,
                        "text": text,
                    })
        return segments

    def _check_rate_limit(self, cache, audio_duration: float):
        """检查限流：100次/12小时，360分钟/12小时"""
        tag = "rate_limit:BcutASREngine"
        time_limit = time.time() - RATE_LIMIT_TIME_WINDOW

        try:
            query = "SELECT key FROM Cache WHERE tag = ? AND store_time >= ?"
            results = cache._sql(query, (tag, time_limit)).fetchall()
        except Exception:
            return  # 缓存查询失败不阻塞流程

        durations = []
        for (key,) in results:
            duration = cache.get(key, default=None)
            if duration is not None and isinstance(duration, (int, float)):
                durations.append(duration)

        call_count = len(durations)
        total_duration = sum(durations)

        if total_duration + audio_duration > RATE_LIMIT_MAX_DURATION:
            raise RuntimeError(
                f"必剪语音识别时长已达上限（{total_duration / 60:.0f}/360 分钟），请 12 小时后再试或切换为本地 Whisper"
            )
        if call_count >= RATE_LIMIT_MAX_CALLS:
            raise RuntimeError(
                f"必剪语音识别次数已达上限（{call_count}/100 次），请 12 小时后再试或切换为本地 Whisper"
            )

    def _record_rate_limit(self, cache, audio_duration: float):
        """记录本次调用"""
        tag = "rate_limit:BcutASREngine"
        cache.set(
            f"rate_limit_record:BcutASREngine:{uuid.uuid4()}",
            audio_duration,
            tag=tag,
            expire=int(RATE_LIMIT_TIME_WINDOW) + 3600,
        )
