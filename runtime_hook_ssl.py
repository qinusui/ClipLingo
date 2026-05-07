# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子：修复打包后的环境问题。
1. 修复 SSL 证书验证失败的问题
2. 修复 console=False 时 sys.stdout/sys.stderr 为 None 的问题
"""
import os
import sys

# 修复 SSL 证书
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
except ImportError:
    pass

# 修复 console=False 时 stdout/stderr 为 None 的问题
# uvicorn 的日志格式化器会调用 isatty()，如果 stdout/stderr 为 None 会报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')
