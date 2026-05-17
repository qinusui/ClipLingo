"""
Whisper 管理模块
faster-whisper 已内置在主程序中，无需额外安装插件。

模型下载优先级:
1. 本地离线模型
2. 打包内置模型
3. ModelScope SDK 下载（国内最快）
4. HuggingFace hub 在线下载（多镜像自动测速）
"""
import os
import sys
import subprocess
import socket
import time
import logging
import shutil

# Windows 下防止子进程弹出终端窗口
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
from pathlib import Path
from typing import Optional, Any, Callable

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

# 默认 API 端点：当下载源不提供 Hub API 时，回退到此端点获取模型文件列表
# （保留此机制以支持未来可能添加的纯下载镜像）
DEFAULT_API_ENDPOINT = "https://hf-mirror.com"

# 下载源优先级：国内镜像优先（默认），海外用户运行时自动调整
# 格式: (api_endpoint, download_url_template, label, probe_host)
# - api_endpoint: HuggingFace Hub API 端点（获取文件列表等元数据）；None 表示使用 DEFAULT_API_ENDPOINT
# - download_url_template: 文件下载 URL 模板；None 表示使用默认模板 {api_endpoint}/{repo_id}/resolve/{revision}/{filename}
# - probe_host: TCP 延迟探测目标（通常是下载服务器）
#
# 注意：清华 TUNA 的 hugging-face-models 镜像已于 2021 年失效，hf-mirror.com 是目前国内推荐的替代。
HF_SOURCES = [
    ("https://hf-mirror.com",                 None, "HF 镜像",              "hf-mirror.com"),
    ("https://huggingface.modelscope.cn",     None, "ModelScope（阿里云）",  "huggingface.modelscope.cn"),
    ("https://huggingface.co",                None, "HuggingFace 主站",     "huggingface.co"),
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

    # 探测所有源的延迟（探测下载服务器）
    probed = []
    for api_ep, url_tpl, label, host in HF_SOURCES:
        latency = _probe_host(host)
        if latency is not None:
            logger.info(f"{label}（{host}）延迟 {latency:.1f}s")
            probed.append((latency, api_ep, label, url_tpl))
        else:
            logger.info(f"{label}（{host}）不可达，降为备选")
            probed.append((999.0, api_ep, label, url_tpl))

    # 按延迟从低到高排序
    probed.sort(key=lambda x: x[0])
    _cached_source_order = [(api_ep, label, url_tpl) for _, api_ep, label, url_tpl in probed]

    first_label = _cached_source_order[0][1]
    first_latency = probed[0][0]
    logger.info(f"选择优先源: {first_label}（{first_latency:.1f}s）")
    return _cached_source_order


def _set_hf_endpoint(api_endpoint: str = None, url_template: str = None):
    """设置 HF_ENDPOINT 并同步更新 huggingface_hub 模块常量

    huggingface_hub.constants 的 ENDPOINT / HUGGINGFACE_CO_URL_TEMPLATE 是模块级常量，
    import 时求值，只改环境变量不会更新。必须同步修改常量，否则文件下载 URL 仍指向旧端点。

    api_endpoint=None 时使用 DEFAULT_API_ENDPOINT（适用于清华镜像等仅有文件下载的源）。
    """
    api = api_endpoint or DEFAULT_API_ENDPOINT
    os.environ["HF_ENDPOINT"] = api
    try:
        import huggingface_hub.constants as hf_const
        hf_const.ENDPOINT = api.rstrip("/")
        if url_template:
            hf_const.HUGGINGFACE_CO_URL_TEMPLATE = url_template
        else:
            hf_const.HUGGINGFACE_CO_URL_TEMPLATE = api.rstrip("/") + "/{repo_id}/resolve/{revision}/{filename}"
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


def _check_bundled_model(model_name: str) -> Optional[Path]:
    """检查打包内置的模型（仅 frozen 模式），返回模型目录路径或 None"""
    if not getattr(sys, 'frozen', False):
        return None
    model_dir = Path(sys._MEIPASS) / "models" / "bundled" / model_name
    model_bin = model_dir / "model.bin"
    if model_bin.exists():
        logger.info(f"检测到内置模型: {model_dir}")
        return model_dir
    return None


def _clear_model_cache(model_name: str):
    """清除指定模型的本地缓存，避免损坏/不完整的缓存阻止重试"""
    try:
        from huggingface_hub import constants as hf_const
        cache_dir = Path(hf_const.HF_HUB_CACHE) / f"models--Systran--faster-whisper-{model_name}"
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
            logger.info(f"已清除损坏的模型缓存: {cache_dir}")
    except Exception:
        pass


def load_model(
    model_name: str = "base",
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Optional[Any]:
    """
    加载 faster-whisper WhisperModel

    下载优先级：
        1. 本地离线模型（%APPDATA%/ClipLingo/models/{model_name}/）
        2. 打包内置模型
        3. ModelScope SDK 下载（国内最快最稳，下载到离线模型目录）
        4. HuggingFace hub 在线下载（根据网络环境自动选择优先源）

    progress_callback(status_message) 可选，用于上报下载进度。
    """

    def _report(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    faster_whisper = get_whisper()
    if faster_whisper is None:
        return None

    _ensure_hf_token()
    _ensure_ssl_cert()

    # 1. 离线模型优先
    offline_path = _check_offline_model(model_name)
    if offline_path is not None:
        try:
            _report(f"加载离线模型: {offline_path}")
            return faster_whisper.WhisperModel(str(offline_path), local_files_only=True)
        except Exception as e:
            logger.warning(f"离线模型加载失败: {e}，尝试内置模型...")

    # 2. 内置模型（打包时预置）
    bundled_path = _check_bundled_model(model_name)
    if bundled_path is not None:
        try:
            _report(f"加载内置模型: {bundled_path}")
            return faster_whisper.WhisperModel(str(bundled_path), local_files_only=True)
        except Exception as e:
            logger.warning(f"内置模型加载失败: {e}，尝试在线下载...")

    # 3. ModelScope SDK 下载 → 离线模型目录（后续启动自动命中离线缓存）
    _report(f"下载 {model_name} 模型（ModelScope）...")
    ms_path = _download_via_modelscope(model_name)
    if ms_path is not None:
        try:
            model = faster_whisper.WhisperModel(str(ms_path), local_files_only=True)
            _report(f"模型加载成功（来源：ModelScope，已缓存到 {ms_path}）")
            return model
        except Exception as e:
            logger.warning(f"ModelScope 模型加载失败: {e}，尝试 HF hub...")
            _clear_offline_model(model_name)

    # 4. HuggingFace hub 在线下载（多镜像自动测速）
    sources = _get_source_order()
    last_error = None
    tried_labels: list[str] = []
    for api_ep, label, url_tpl in sources:
        if last_error is not None:
            _clear_model_cache(model_name)
        _set_hf_endpoint(api_ep, url_tpl)
        tried_labels.append(label)
        try:
            _report(f"从 {label} 下载模型 {model_name}...")
            model = faster_whisper.WhisperModel(model_name)
            _report(f"模型下载成功（来源：{label}）")
            return model
        except Exception as e:
            logger.warning(f"{label} 下载失败: {str(e)[:100]}")
            last_error = e

    # 5. 全部源都失败 → 给用户可操作的提示
    offline_dir = LOCAL_MODEL_DIR / model_name
    tried_str = " → ".join(tried_labels)
    raise ClipLingoError(ErrorCode.WHISPER_MODEL_FAILED,
        f"所有下载源均失败（{tried_str}）\n"
        f"离线模型目录: {offline_dir}\n"
        f"手动下载地址: https://hf-mirror.com/Systran/faster-whisper-{model_name}\n"
        f"           或 https://huggingface.modelscope.cn/Systran/faster-whisper-{model_name}\n"
        f"下载后把 model.bin 等文件放入上述目录即可")


def _download_via_modelscope(model_name: str) -> Optional[Path]:
    """通过 model_downloader 从 ModelScope 下载模型，返回模型目录路径或 None"""
    dest_dir = LOCAL_MODEL_DIR / model_name

    # 检查是否已有可用模型（可能之前下载中断但部分文件存在）
    model_bin = dest_dir / "model.bin"
    if model_bin.exists():
        return dest_dir

    try:
        from core.model_downloader import download_whisper_model
        return download_whisper_model(model_name, dest_dir)
    except ImportError as e:
        logger.warning(f"无法导入 model_downloader: {e}")
        return None
    except Exception as e:
        logger.warning(f"ModelScope 下载流程异常: {e}")
        return None


def _clear_offline_model(model_name: str):
    """清除本地离线模型目录（用于 ModelScope 下载失败后清理）"""
    model_dir = LOCAL_MODEL_DIR / model_name
    if model_dir.exists():
        shutil.rmtree(model_dir, ignore_errors=True)
        logger.info(f"已清除离线模型: {model_dir}")
