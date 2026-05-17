# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子：修复打包后的环境问题。
1. 强制 UTF-8 模式，解决中文路径安装失败的问题
2. 修复 SSL 证书验证失败的问题
3. 修复 console=False 时 sys.stdout/sys.stderr 为 None 的问题
"""
import os
import sys

# ── 强制 UTF-8 模式（必须在其他导入之前） ──
if sys.platform == "win32":
    # PYTHONIOENCODING 影响 subprocess text=True 时的默认编码
    if not os.environ.get("PYTHONIOENCODING"):
        os.environ["PYTHONIOENCODING"] = "utf-8"
    # PYTHONUTF8 影响 Python 的文件 I/O 默认编码（Python 3.7+）
    if not os.environ.get("PYTHONUTF8"):
        os.environ["PYTHONUTF8"] = "1"

    # 重配 stdio 为 UTF-8（用 reconfigure 避免 TextIOWrapper GC 关闭 buffer）
    for _name in ("stdout", "stderr", "stdin"):
        _stream = getattr(sys, _name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# ── 修复 console=False 时 stdout/stderr 为 None 的问题 ──
# uvicorn 的日志格式化器会调用 isatty()，如果 stdout/stderr 为 None 会报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# ── 添加 DLL 搜索路径，确保子进程能找到 ctranslate2/onnxruntime 等原生模块 ──
if getattr(sys, 'frozen', False):
    try:
        os.add_dll_directory(sys._MEIPASS)
    except Exception:
        pass

    # 防止 Intel OpenMP 库（libiomp5md.dll）重复加载冲突导致 0xC0000005 崩溃
    if sys.platform == "win32":
        try:
            os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        except Exception:
            pass

# ── 修复 SSL 证书 ──
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
except ImportError:
    pass
