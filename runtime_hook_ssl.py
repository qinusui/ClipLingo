# -*- coding: utf-8 -*-
"""
PyInstaller 运行时钩子：修复打包后 SSL 证书验证失败的问题。
在程序启动时设置 SSL_CERT_FILE 环境变量，指向 certifi 的 CA 证书包。
"""
import os
import sys

try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
except ImportError:
    pass
