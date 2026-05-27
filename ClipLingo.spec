# -*- mode: python ; coding: utf-8 -*-
import os
import sys

VERSION = "1.4.5.0"

block_cipher = None

# 获取 frontend/dist 的绝对路径
frontend_dist = os.path.join(os.path.dirname(os.path.abspath(SPEC)), 'frontend', 'dist')

# faster_whisper 包路径和资源
import faster_whisper as _fw
_fw_dir = os.path.dirname(_fw.__file__)
fw_assets = os.path.join(_fw_dir, 'assets')
# 收集 faster_whisper 的 .py 源文件，确保打包后文件系统上有完整包
_fw_datas = [(os.path.join(_fw_dir, f), 'faster_whisper')
             for f in os.listdir(_fw_dir)
             if f.endswith('.py')]

# 收集 ctranslate2 的全部 DLL（PyInstaller 可能遗漏 cudnn64_9.dll）
import ctranslate2 as _ct2
_ct2_dir = os.path.dirname(_ct2.__file__)
_ct2_binaries = [(os.path.join(_ct2_dir, f), 'ctranslate2')
                 for f in os.listdir(_ct2_dir)
                 if f.endswith('.dll')]

a = Analysis(
    ['backend/main.py'],
    pathex=['backend', '.'],
    binaries=[
        ('bin/ffmpeg.exe', 'bin'),
        ('bin/ffprobe.exe', 'bin'),
        *_ct2_binaries,
    ],
    datas=[
        (frontend_dist, 'frontend/dist'),
        ('core', 'core'),
        (fw_assets, 'faster_whisper/assets'),
        *_fw_datas,
    ],
    hiddenimports=[
        'fastapi',
        'fastapi.staticfiles',
        'starlette',
        'starlette.routing',
        'starlette.responses',
        'starlette.middleware',
        'starlette.middleware.cors',
        'api',
        'api.subtitles',
        'api.process',
        'api.cards',
        'models',
        'models.schemas',
        'services',
        'core',
        'core.ai_process',
        'core.media_cut',
        'core.pack_apkg',
        'core.parse_srt',
        'core.whisper_manager',
        'core.asr',
        'core.asr.base',
        'core.asr.whisper_engine',
        'core.asr.bcut_engine',
        'core.asr.chunked_asr',
        'core.translate',
        'core.translate.base',
        'core.translate.bing',
        'core.translate.google',
        'diskcache',
        'faster_whisper',
        'ctranslate2',
        'onnxruntime',
        'numpy',
        'huggingface_hub',
        'openai',
        'genanki',
        'pysrt',
        'dotenv',
        'certifi',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook_ssl.py'],
    excludes=[
        'paddlepaddle', 'paddleocr', 'cv2', 'opencv',
        'whisper', 'openai-whisper',
        'torch', 'torchvision', 'torchaudio',
        'PIL', 'pillow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClipLingo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='frontend\\public\\favicon.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClipLingo',
)
