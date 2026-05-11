"""
Whisper 管理模块
faster-whisper 已内置在主程序中，无需额外安装插件。
"""
import os
import sys
import subprocess
import logging

# Windows 下防止子进程弹出终端窗口
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
from pathlib import Path
from typing import Optional, Any

# 确保项目根目录在 sys.path 中
_root = str(Path(__file__).parent.parent)
if _root not in sys.path:
    sys.path.append(_root)

from errors import ClipLingoError, ErrorCode

logger = logging.getLogger(__name__)


def is_whisper_installed() -> bool:
    """检查 whisper 是否可用"""
    try:
        import faster_whisper  # noqa: F811
        return True
    except ImportError:
        return False


def install_whisper() -> tuple[bool, str]:
    """
    安装 faster-whisper
    - 打包模式：已内置，无需安装
    - 开发模式：在当前 Python 环境安装
    返回 (是否安装成功, 错误信息)
    """
    if getattr(sys, 'frozen', False):
        return True, "Whisper 已内置，请直接使用"

    # 开发模式：用 pip 安装
    _PIP_SOURCES = [
        ("https://pypi.org/simple/", "pypi.org"),
        ("https://pypi.tuna.tsinghua.edu.cn/simple", "pypi.tuna.tsinghua.edu.cn"),
        ("https://mirrors.aliyun.com/pypi/simple/", "mirrors.aliyun.com"),
    ]

    last_error = ""
    for source_url, host in _PIP_SOURCES:
        logger.info(f"尝试从 {source_url} 安装 faster-whisper...")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install",
                 "faster-whisper",
                 "-i", source_url,
                 "--trusted-host", host,
                 "--timeout", "30"],
                capture_output=True, encoding='utf-8', errors='replace', timeout=600,
                **_NO_WINDOW
            )
            if result.returncode == 0:
                return True, ""
            last_error = result.stderr[:500] or "pip install 失败"
            logger.warning(f"从 {source_url} 安装失败: {last_error}")
        except subprocess.TimeoutExpired:
            last_error = f"从 {source_url} 安装超时"
        except Exception as e:
            last_error = str(e)[:500]

    return False, f"安装失败: {last_error}"


def get_whisper() -> Optional[Any]:
    """获取 faster_whisper 模块"""
    try:
        import faster_whisper
        return faster_whisper
    except ImportError:
        return None


def load_model(model_name: str = "base") -> Optional[Any]:
    """加载 faster-whisper WhisperModel（下载失败自动走镜像重试）"""
    # 确保 huggingface token 文件存在，避免 OSError
    token_path = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "token")
    if not os.path.exists(token_path):
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        open(token_path, "w").close()

    # 修复 PyInstaller 打包后 SSL 证书验证失败的问题
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass

    faster_whisper = get_whisper()
    if faster_whisper is None:
        return None

    def _try_load():
        return faster_whisper.WhisperModel(model_name)

    # 网络错误关键词（huggingface_hub / requests / urllib3 常见错误）
    _NET_ERR = ("timeout", "connection", "unreachable", "refused", "reset",
                "host", "network", "dns", "getaddrinfo", "name or service",
                "tls", "ssl", "certificate", "eof", "broken pipe",
                "nodata", "no data", "403", "502", "503")

    def _is_network_error(err: Exception) -> bool:
        msg = str(err).lower()
        return any(kw in msg for kw in _NET_ERR)

    try:
        return _try_load()
    except Exception as first_err:
        if not _is_network_error(first_err):
            raise ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED, str(first_err)[:200])

        # 网络错误 → 切换 HuggingFace 镜像重试
        mirror = "https://hf-mirror.com"
        logger.info(f"模型下载失败（{str(first_err)[:100]}），尝试镜像 {mirror}")
        old_endpoint = os.environ.get("HF_ENDPOINT")
        os.environ["HF_ENDPOINT"] = mirror
        try:
            return _try_load()
        except Exception as second_err:
            # 恢复旧值
            if old_endpoint is not None:
                os.environ["HF_ENDPOINT"] = old_endpoint
            else:
                os.environ.pop("HF_ENDPOINT", None)
            raise ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED,
                                f"镜像重试也失败: {str(second_err)[:150]}")
        if old_endpoint is None:
            os.environ.pop("HF_ENDPOINT", None)
