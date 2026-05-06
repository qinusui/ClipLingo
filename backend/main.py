"""
ClipLingo - FastAPI 后端服务
提供 RESTful API 供前端调用
"""

import sys
from pathlib import Path

# 检测是否在 PyInstaller 打包环境中运行
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的路径
    BASE_DIR = Path(sys._MEIPASS)
    INSTALL_DIR = Path(sys.executable).parent
else:
    # 正常 Python 运行的路径
    BASE_DIR = Path(__file__).parent
    INSTALL_DIR = BASE_DIR.parent  # 项目根目录，与 process.py 的输出目录一致

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import json
import signal
import logging
import threading
import time
from datetime import datetime
from dotenv import load_dotenv

# 静默轮询日志
class PollingFilter(logging.Filter):
    _silent_paths = ('/progress/', '/ai-recommend/progress/', '/transcribe/progress/')

    def filter(self, record):
        msg = record.getMessage()
        return not any(p in msg for p in self._silent_paths)

logging.getLogger("uvicorn.access").addFilter(PollingFilter())

from api.subtitles import router as subtitles_router
from api.process import router as process_router
from api.cards import router as cards_router

load_dotenv()

# ---- 自动关闭机制 ----
_server_start_time = time.time()
_SHUTDOWN_COOLDOWN = 30  # 启动后 30 秒内的 shutdown 请求忽略（避免 HMR 重载误触）


def _kill_processes():
    """读取 PID 文件并关闭前后端进程"""
    pid_file = Path(__file__).parent / 'pids.json'
    if not pid_file.exists():
        return
    try:
        pids = json.loads(pid_file.read_text())
    except Exception:
        return

    for key in ('frontend_pid', 'backend_pid'):
        pid = pids.get(key)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    pid_file.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Anki Card Generator API",
    description="智能提取视频学习内容，生成 Anki 卡片",
    version="1.2.1",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载输出目录供下载和预览（写到安装目录，不是 _internal）
output_dir = INSTALL_DIR / "output"
output_dir.mkdir(exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir)), name="output")

# 挂载前端构建产物
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后，前端在 _internal/frontend/dist
    frontend_dist = BASE_DIR / "frontend" / "dist"
else:
    # 正常运行时，前端在项目根目录的 frontend/dist
    frontend_dist = BASE_DIR.parent / "frontend" / "dist"

if frontend_dist.exists():
    # 挂载 assets 目录（JS、CSS）
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

# 注册路由
app.include_router(subtitles_router, prefix="/api/subtitles", tags=["subtitles"])
app.include_router(process_router, prefix="/api/process", tags=["process"])
app.include_router(cards_router, prefix="/api/cards", tags=["cards"])


@app.post("/api/shutdown")
async def shutdown():
    """关闭所有服务（仅打包模式生效，启动冷却期内忽略）"""
    pid_file = BASE_DIR / 'pids.json'
    if not pid_file.exists():
        return {"message": "Ignored (dev mode)"}
    if time.time() - _server_start_time < _SHUTDOWN_COOLDOWN:
        return {"message": "Ignored (cooldown)"}
    _kill_processes()
    os._exit(0)


# ---- 业务路由 ----

@app.get("/")
async def root():
    # Docker 模式下返回前端页面
    frontend_index = frontend_dist / "index.html"
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return {
        "message": "ClipLingo API",
        "version": "1.2.1",
        "docs": "/docs"
    }


@app.get("/favicon.ico")
async def favicon_ico():
    """返回 favicon.ico"""
    favicon_path = frontend_dist / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path, media_type="image/x-icon")
    raise HTTPException(status_code=404)


@app.get("/favicon.svg")
async def favicon_svg():
    """返回 favicon.svg"""
    favicon_path = frontend_dist / "favicon.svg"
    if favicon_path.exists():
        return FileResponse(favicon_path, media_type="image/svg+xml")
    raise HTTPException(status_code=404)


@app.get("/favicon-96x96.png")
async def favicon_png():
    """返回 favicon-96x96.png"""
    favicon_path = frontend_dist / "favicon-96x96.png"
    if favicon_path.exists():
        return FileResponse(favicon_path, media_type="image/png")
    raise HTTPException(status_code=404)


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    """返回 apple-touch-icon.png"""
    icon_path = frontend_dist / "apple-touch-icon.png"
    if icon_path.exists():
        return FileResponse(icon_path, media_type="image/png")
    raise HTTPException(status_code=404)


@app.get("/site.webmanifest")
async def site_webmanifest():
    """返回 site.webmanifest"""
    manifest_path = frontend_dist / "site.webmanifest"
    if manifest_path.exists():
        return FileResponse(manifest_path, media_type="application/manifest+json")
    raise HTTPException(status_code=404)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/download/{filename}")
async def download_file(filename: str):
    """下载生成的文件"""
    file_path = output_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)


def _open_browser():
    """延迟打开浏览器"""
    import webbrowser
    time.sleep(2)  # 等待服务器启动
    webbrowser.open('http://localhost:8000')


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    # Docker 或 PyInstaller 中禁用 reload
    is_docker = os.environ.get('DOCKER_CONTAINER') == '1'
    is_frozen = getattr(sys, 'frozen', False)

    if is_docker or is_frozen:
        # 打包模式下自动打开浏览器
        if is_frozen:
            threading.Thread(target=_open_browser, daemon=True).start()
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    else:
        uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
