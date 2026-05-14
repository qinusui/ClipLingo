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

# 离线模型目录：frozen 模式用 %APPDATA%，开发模式用项目根目录
if getattr(sys, 'frozen', False):
    LOCAL_MODEL_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo' / 'models'
else:
    LOCAL_MODEL_DIR = Path(__file__).parent.parent / 'models'

# 下载源优先级：国内镜像优先
HF_SOURCES = [
    ("https://hf-mirror.com",   "HF 镜像"),
    ("https://huggingface.co",  "HuggingFace 主站"),
]


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


def _ensure_hf_token():
    """确保 huggingface token 文件存在，避免 OSError"""
    token_path = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "token")
    if not os.path.exists(token_path):
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        open(token_path, "w").close()


def _ensure_ssl_cert():
    """修复 PyInstaller 打包后 SSL 证书验证失败的问题"""
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except ImportError:
            pass


def _check_offline_model(model_name: str) -> Optional[Path]:
    """检查本地是否有离线模型文件，返回模型目录路径或 None"""
    model_dir = LOCAL_MODEL_DIR / model_name
    model_bin = model_dir / "model.bin"
    if model_bin.exists():
        logger.info(f"检测到离线模型: {model_dir}")
        return model_dir
    return None


def load_model(model_name: str = "base") -> Optional[Any]:
    """
    加载 faster-whisper WhisperModel

    下载优先级：
        1. 本地离线模型（%APPDATA%/ClipLingo/models/{model_name}/）
        2. HF 镜像（hf-mirror.com，国内优化）
        3. HuggingFace 主站
    """
    faster_whisper = get_whisper()
    if faster_whisper is None:
        return None

    _ensure_hf_token()
    _ensure_ssl_cert()

    # 1. 离线模型优先
    offline_path = _check_offline_model(model_name)
    if offline_path is not None:
        try:
            return faster_whisper.WhisperModel(str(offline_path), local_files_only=True)
        except Exception as e:
            logger.warning(f"离线模型加载失败: {e}，尝试在线下载...")

    # 2. 依次尝试在线下载源
    last_error = None
    for endpoint, label in HF_SOURCES:
        os.environ["HF_ENDPOINT"] = endpoint
        try:
            logger.info(f"从 {label} 下载模型 {model_name}...")
            model = faster_whisper.WhisperModel(model_name)
            logger.info(f"模型下载成功（来源：{label}）")
            return model
        except Exception as e:
            logger.warning(f"{label} 下载失败: {str(e)[:100]}")
            last_error = e

    # 3. 全部源都失败 → 给用户可操作的提示
    offline_dir = LOCAL_MODEL_DIR / model_name
    raise ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED,
        f"所有下载源均失败\n"
        f"离线模型目录: {offline_dir}\n"
        f"手动下载地址: https://hf-mirror.com/Systran/faster-whisper-{model_name}\n"
        f"下载后把 model.bin 等文件放入上述目录即可")
