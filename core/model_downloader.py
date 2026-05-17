"""
模型下载模块 - 统一的模型文件下载，支持 aria2c 加速、多源 fallback、进度回调

为 faster-whisper 模型提供多重下载路径:
1. ModelScope SDK (snapshot_download) — 国内用户最快
2. aria2c 多线程直链下载 — 大文件加速
3. requests 流式下载 — 通用回退，支持细粒度进度
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# 无窗口标记，避免 Windows 下子进程弹出终端
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

# ---------- faster-whisper 模型在 ModelScope 上的 ID 映射 ----------

MODELSCOPE_MODEL_MAP: dict[str, str] = {
    "tiny": "pengzhendong/faster-whisper-tiny",
    "tiny.en": "pengzhendong/faster-whisper-tiny.en",
    "base": "pengzhendong/faster-whisper-base",
    "base.en": "pengzhendong/faster-whisper-base.en",
    "small": "pengzhendong/faster-whisper-small",
    "small.en": "pengzhendong/faster-whisper-small.en",
    "medium": "pengzhendong/faster-whisper-medium",
    "medium.en": "pengzhendong/faster-whisper-medium.en",
    "large-v1": "pengzhendong/faster-whisper-large-v1",
    "large-v2": "pengzhendong/faster-whisper-large-v2",
    "large-v3": "pengzhendong/faster-whisper-large-v3",
}

# 模型文件直链下载源（按优先级排列）
_MODEL_DOWNLOAD_SOURCES = [
    ("https://hf-mirror.com", "HF 镜像"),
    ("https://huggingface.modelscope.cn", "ModelScope HF"),
]


def find_aria2c() -> Optional[str]:
    """在 PATH 和常见路径中查找 aria2c"""
    for name in ["aria2c", "aria2c.exe"]:
        found = shutil.which(name)
        if found:
            return found

    # Windows 常见安装路径
    if sys.platform == "win32":
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "aria2c"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "aria2c"),
            os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "shims", "aria2c.exe"),
        ]
        for c in candidates:
            exe = c if c.endswith(".exe") else os.path.join(c, "aria2c.exe")
            if os.path.exists(exe):
                return exe
    return None


def _get_total_size(url: str, timeout: float = 10.0) -> int:
    """通过 HEAD 请求获取文件总大小（字节），失败返回 0"""
    try:
        import requests as _requests
        resp = _requests.head(url, timeout=timeout, allow_redirects=True)
        return int(resp.headers.get("content-length", 0))
    except Exception:
        return 0


# ---------- 直链下载 ----------


def download_file(
    url: str,
    dest: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 1800,
) -> bool:
    """
    下载单个文件，优先 aria2c，否则 requests。

    progress_callback(downloaded_bytes, total_bytes)
    total_bytes 在 aria2c 模式下可能为 0（未知总大小）。

    返回 True 表示下载成功。
    """
    aria2c = find_aria2c()
    if aria2c:
        logger.info(f"使用 aria2c ({aria2c}) 下载")
        return _download_with_aria2c(aria2c, url, dest, progress_callback, timeout)
    else:
        logger.info("aria2c 未找到，使用 requests 下载")
        return _download_with_requests(url, dest, progress_callback, timeout)


def _download_with_requests(
    url: str,
    dest: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 1800,
) -> bool:
    """使用 requests 流式下载，支持实时进度回调"""
    import requests as _requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    try:
        resp = _requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)

        tmp.replace(dest)
        if progress_callback and total > 0:
            progress_callback(total, total)
        return True

    except Exception as e:
        logger.error(f"requests 下载失败: {e}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False


def _download_with_aria2c(
    aria2c: str,
    url: str,
    dest: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: int = 1800,
) -> bool:
    """
    使用 aria2c 多线程下载，通过轮询文件大小报告进度。
    aria2c 自动支持断点续传（.aria2 控制文件）。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # 尝试获取总大小用于进度报告
    total = _get_total_size(url)

    cmd = [
        aria2c,
        url,
        "-d", str(dest.parent),
        "-o", dest.name,
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--console-log-level=warn",
        "--summary-interval=0",
        "--file-allocation=none",
        "--allow-overwrite=true",
    ]

    try:
        proc = subprocess.Popen(cmd, **_NO_WINDOW)

        # 轮询文件大小，报告进度
        last_size = 0
        stall_count = 0
        while proc.poll() is None:
            time.sleep(1)
            part = dest.with_name(dest.name + ".aria2")
            actual = dest
            if actual.exists():
                size = actual.stat().st_size
                if progress_callback and size != last_size:
                    progress_callback(size, total)
                    last_size = size
                    stall_count = 0
                elif size == last_size:
                    stall_count += 1
            else:
                stall_count += 1

            if stall_count > timeout:
                proc.terminate()
                logger.error("aria2c 下载超时（无进度）")
                return False

        if proc.returncode != 0:
            logger.error(f"aria2c 异常退出，返回码 {proc.returncode}")
            return False

        if progress_callback and total > 0:
            progress_callback(total, total)
        return True

    except Exception as e:
        logger.error(f"aria2c 下载失败: {e}")
        return False


# ---------- ModelScope SDK 下载 ----------


def download_from_modelscope(
    model_id: str,
    local_dir: Path,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> bool:
    """
    通过 ModelScope SDK 下载完整模型仓库。

    progress_callback(progress_percentage, status_message)
    """
    try:
        from modelscope.hub.api import HubApi
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        logger.warning("modelscope 未安装，无法使用 ModelScope 下载")
        return False

    local_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"ModelScope 下载 {model_id} -> {local_dir}")

    try:
        snapshot_download(model_id, local_dir=str(local_dir))
        if progress_callback:
            progress_callback(100, "ModelScope 下载完成")
        logger.info(f"ModelScope 下载成功: {model_id}")
        return True
    except Exception as e:
        logger.warning(f"ModelScope 下载失败 ({model_id}): {e}")
        # 清除可能留下的不完整文件
        if local_dir.exists():
            shutil.rmtree(local_dir, ignore_errors=True)
        return False


# ---------- 高层接口 ----------


def download_whisper_model(
    model_name: str,
    dest_dir: Path,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Optional[Path]:
    """
    下载 faster-whisper 模型到指定目录，自动选择最佳下载方式。

    下载优先级:
    1. ModelScope SDK（国内用户最快最稳）
    2. HF 镜像直链下载（aria2c / requests）

    progress_callback(downloaded_or_percent, status_message)

    返回模型目录路径，失败返回 None。
    """
    # 方式 1: ModelScope SDK
    model_id = MODELSCOPE_MODEL_MAP.get(model_name)
    if model_id:
        logger.info(f"尝试 ModelScope 下载: {model_id}")
        if progress_callback:
            progress_callback(0, f"ModelScope 下载 {model_name} 模型...")
        if download_from_modelscope(model_id, dest_dir):
            return dest_dir
        logger.info(f"ModelScope 下载失败，尝试直链下载...")

    # 方式 2: 直链下载（model.bin 等文件从 HF 镜像逐个下载）
    # faster-whisper 模型通常需要 model.bin, config.json, tokenizer.json, vocabulary.txt
    hf_repo = f"Systran/faster-whisper-{model_name}"
    files = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]

    for source_url, label in _MODEL_DOWNLOAD_SOURCES:
        logger.info(f"尝试从 {label} 下载模型文件...")
        if progress_callback:
            progress_callback(0, f"从 {label} 下载 {model_name} 模型...")

        all_ok = True
        total_files = len(files)
        for idx, filename in enumerate(files):
            url = f"{source_url}/{hf_repo}/resolve/main/{filename}"
            dest_file = dest_dir / filename

            # 跳过已存在的文件（可能是断点续传）
            if dest_file.exists() and filename != "model.bin":
                continue

            if progress_callback:
                progress_callback(
                    int(idx / total_files * 100), f"下载 {filename} ({idx + 1}/{total_files})"
                )

            if not download_file(url, dest_file):
                all_ok = False
                break

        if all_ok:
            logger.info(f"直链下载成功 ({label})")
            if progress_callback:
                progress_callback(100, f"模型 {model_name} 下载完成")
            return dest_dir
        else:
            logger.warning(f"{label} 下载失败，尝试下一源")

    return None
