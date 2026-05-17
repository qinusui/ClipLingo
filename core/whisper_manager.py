"""
Whisper 管理模块
faster-whisper 已内置在主程序中，无需额外安装插件。
"""
import os
import sys
import subprocess
import socket
import time
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

# 下载源优先级：国内镜像优先（默认），海外用户运行时自动调整
# 格式: (endpoint, label, host_for_probe, url_template_override)
# url_template_override 为 None 时使用默认模板 {endpoint}/{repo_id}/resolve/{revision}/{filename}
HF_SOURCES = [
    ("https://hf-mirror.com",                                   "HF 镜像",              "hf-mirror.com",                       None),
    ("https://mirrors.tuna.tsinghua.edu.cn/hugging-face-hub",   "清华镜像",             "mirrors.tuna.tsinghua.edu.cn",         "https://mirrors.tuna.tsinghua.edu.cn/hugging-face-models/{repo_id}/resolve/{revision}/{filename}"),
    ("https://huggingface.modelscope.cn",                       "ModelScope（阿里云）",  "huggingface.modelscope.cn",            None),
    ("https://huggingface.co",                                  "HuggingFace 主站",     "huggingface.co",                       None),
]

# 缓存探测结果，避免每次下载都重新测速
_cached_source_order: Optional[list] = None


def _probe_host(host: str, port: int = 443, timeout: float = 3.0) -> Optional[float]:
    """TCP 连通性探测，返回延迟秒数；不可达返回 None"""
    try:
        start = time.time()
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return time.time() - start
    except Exception:
        return None


def _get_source_order() -> list:
    """根据网络环境自动确定下载源优先级（按延迟从低到高排序），结果会话级缓存"""
    global _cached_source_order
    if _cached_source_order is not None:
        return _cached_source_order

    # 探测所有源的延迟
    probed = []
    for endpoint, label, host, url_tpl in HF_SOURCES:
        latency = _probe_host(host)
        if latency is not None:
            logger.info(f"{label}（{host}）延迟 {latency:.1f}s")
            probed.append((latency, endpoint, label, url_tpl))
        else:
            logger.info(f"{label}（{host}）不可达，降为备选")
            probed.append((999.0, endpoint, label, url_tpl))

    # 按延迟从低到高排序
    probed.sort(key=lambda x: x[0])
    _cached_source_order = [(endpoint, label, url_tpl) for _, endpoint, label, url_tpl in probed]

    first_label = _cached_source_order[0][1]
    first_latency = probed[0][0]
    logger.info(f"选择优先源: {first_label}（{first_latency:.1f}s）")
    return _cached_source_order


def _set_hf_endpoint(endpoint: str, url_template: str = None):
    """设置 HF_ENDPOINT 并同步更新 huggingface_hub 模块常量

    huggingface_hub.constants 的 ENDPOINT / HUGGINGFACE_CO_URL_TEMPLATE 是模块级常量，
    import 时求值，只改环境变量不会更新。必须同步修改常量，否则文件下载 URL 仍指向旧端点。
    """
    os.environ["HF_ENDPOINT"] = endpoint
    try:
        import huggingface_hub.constants as hf_const
        hf_const.ENDPOINT = endpoint.rstrip("/")
        if url_template:
            hf_const.HUGGINGFACE_CO_URL_TEMPLATE = url_template
        else:
            hf_const.HUGGINGFACE_CO_URL_TEMPLATE = endpoint.rstrip("/") + "/{repo_id}/resolve/{revision}/{filename}"
    except ImportError:
        pass


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
        2. 在线下载（根据网络环境自动选择优先源：国内→hf-mirror，海外→huggingface.co）
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

    # 2. 依次尝试在线下载源（根据网络环境自动排序）
    sources = _get_source_order()
    last_error = None
    tried_labels = []
    for endpoint, label, url_tpl in sources:
        _set_hf_endpoint(endpoint, url_tpl)
        tried_labels.append(label)
        try:
            logger.info(f"从 {label}（{endpoint}）下载模型 {model_name}...")
            model = faster_whisper.WhisperModel(model_name)
            logger.info(f"模型下载成功（来源：{label}）")
            return model
        except Exception as e:
            logger.warning(f"{label} 下载失败: {str(e)[:100]}")
            last_error = e

    # 3. 全部源都失败 → 给用户可操作的提示
    offline_dir = LOCAL_MODEL_DIR / model_name
    tried_str = " → ".join(tried_labels)
    raise ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED,
        f"所有下载源均失败（{tried_str}）\n"
        f"离线模型目录: {offline_dir}\n"
        f"手动下载地址: https://hf-mirror.com/Systran/faster-whisper-{model_name}\n"
        f"           或 https://mirrors.tuna.tsinghua.edu.cn/hugging-face-models/Systran/faster-whisper-{model_name}\n"
        f"下载后把 model.bin 等文件放入上述目录即可")
