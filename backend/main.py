"""
ClipLingo - FastAPI 后端服务
提供 RESTful API 供前端调用
"""

import sys
import os

# ── 最早阶段：强制 UTF-8 模式（开发模式无 runtime hook 时兜底） ──
if sys.platform == "win32":
    if not os.environ.get("PYTHONIOENCODING"):
        os.environ["PYTHONIOENCODING"] = "utf-8"
    if not os.environ.get("PYTHONUTF8"):
        os.environ["PYTHONUTF8"] = "1"
    for _name in ("stdout", "stderr", "stdin"):
        _stream = getattr(sys, _name, None)
        if _stream is not None and hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

import logging
from pathlib import Path

# 检测是否在 PyInstaller 打包环境中运行
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的路径
    BASE_DIR = Path(sys._MEIPASS)
    INSTALL_DIR = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / 'ClipLingo'
else:
    # 正常 Python 运行的路径
    BASE_DIR = Path(__file__).parent
    INSTALL_DIR = BASE_DIR.parent  # 项目根目录，与 process.py 的输出目录一致

# ---- 日志配置（必须在其他模块导入之前） ----
LOG_DIR = INSTALL_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "clipplingo.log"

from logging.handlers import RotatingFileHandler

# 静默轮询日志
class PollingFilter(logging.Filter):
    _silent_paths = ('/progress/', '/ai-recommend/progress/', '/transcribe/progress/')

    def filter(self, record):
        msg = record.getMessage()
        return not any(p in msg for p in self._silent_paths)

# 配置根 logger：同时输出到文件和控制台
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)

_file_handler = RotatingFileHandler(
    str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
_root_logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_root_logger.addHandler(_console_handler)

# uvicorn.access 的轮询日志在文件和控制台都静默
_polling_filter = PollingFilter()
logging.getLogger("uvicorn.access").addFilter(_polling_filter)

logger = logging.getLogger(__name__)
logger.info(f"日志文件: {LOG_FILE}")

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import json
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from dotenv import load_dotenv

from api.subtitles import router as subtitles_router
from api.process import router as process_router
from api.cards import router as cards_router
from api.themes import router as themes_router
from api.annotate import router as annotate_router
from api.style_generator import router as style_generator_router

load_dotenv()

# ---- 自动关闭机制 ----
_server_start_time = time.time()
_SHUTDOWN_COOLDOWN = 10  # 启动后 10 秒内的 shutdown 请求忽略（避免 HMR 重载误触）
_last_heartbeat = time.time()
_HEARTBEAT_TIMEOUT = 120  # 2 分钟无心跳自动关闭（仅打包模式）

is_frozen = getattr(sys, 'frozen', False)


def _kill_processes():
    """读取 PID 文件并关闭前后端进程（仅 dev 模式 start-all.py 启动时使用）"""
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


def _heartbeat_monitor():
    """后台线程：心跳超时自动关闭（仅打包模式）"""
    global _last_heartbeat
    if not is_frozen:
        return
    while True:
        time.sleep(30)
        if time.time() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
            logger.info(f"心跳超时 {_HEARTBEAT_TIMEOUT}s，自动关闭")
            os._exit(0)


def _cleanup_old_outputs(output_dir: Path, max_age_hours: int = 24):
    """启动时清理过期任务目录和遗留文件"""
    if not output_dir.exists():
        return
    uuid_re = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    now = time.time()
    max_age_sec = max_age_hours * 3600
    cleaned = 0

    for entry in output_dir.iterdir():
        if not entry.is_dir():
            continue
        # 清理 UUID 格式的任务目录（过期则删除）
        if uuid_re.match(entry.name):
            try:
                mtime = entry.stat().st_mtime
                if now - mtime > max_age_sec:
                    shutil.rmtree(entry, ignore_errors=True)
                    cleaned += 1
            except OSError:
                pass
        # 清理根级遗留的 screenshots/ 和 audio/（新代码已改用 output/{task_id}/ 子目录）
        elif entry.name in ('screenshots', 'audio'):
            try:
                shutil.rmtree(entry, ignore_errors=True)
                cleaned += 1
            except OSError:
                pass

    if cleaned:
        logger.info(f"启动清理完成：移除 {cleaned} 个过期/遗留目录")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时清理过期任务目录
    _cleanup_old_outputs(output_dir)
    yield


app = FastAPI(
    title="Anki Card Generator API",
    description="智能提取视频学习内容，生成 Anki 卡片",
    version="1.4.1",
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
output_dir.mkdir(parents=True, exist_ok=True)
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

# 挂载文档图片目录（用于卡片预览占位等）
if getattr(sys, 'frozen', False):
    docs_dir = BASE_DIR / "docs"
else:
    docs_dir = BASE_DIR.parent / "docs"
if docs_dir.exists():
    app.mount("/docs", StaticFiles(directory=str(docs_dir)), name="docs")

# 注册路由
app.include_router(subtitles_router, prefix="/api/subtitles", tags=["subtitles"])
app.include_router(process_router, prefix="/api/process", tags=["process"])
app.include_router(cards_router, prefix="/api/cards", tags=["cards"])
app.include_router(themes_router, prefix="/api/themes", tags=["themes"])
app.include_router(annotate_router, prefix="/api/annotate", tags=["annotate"])
app.include_router(style_generator_router, prefix="/api/style-generator", tags=["style-generator"])


@app.post("/api/shutdown")
async def shutdown():
    """关闭所有服务（启动冷却期内忽略）"""
    if time.time() - _server_start_time < _SHUTDOWN_COOLDOWN:
        return {"message": "Ignored (cooldown)"}
    logger.info("收到 shutdown 请求，正在关闭...")
    _kill_processes()
    os._exit(0)


@app.post("/api/heartbeat")
async def heartbeat():
    """浏览器心跳，用于检测浏览器是否存活"""
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"status": "ok"}


@app.post("/api/anki-connect")
async def anki_connect_proxy(request: dict):
    """代理 AnkiConnect 请求，避免浏览器 CORS 限制"""
    import urllib.request
    try:
        data = json.dumps(request).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:8765",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"result": None, "error": str(e)}


# ---- 业务路由 ----

@app.get("/")
async def root():
    # Docker 模式下返回前端页面
    frontend_index = frontend_dist / "index.html"
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return {
        "message": "ClipLingo API",
        "version": "1.4.1",
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


@app.post("/api/open-logs")
async def open_logs_folder():
    """打开日志文件夹"""
    try:
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(LOG_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(LOG_DIR)])
        return {"success": True, "path": str(LOG_DIR)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法打开文件夹: {e}")


@app.get("/api/check-update")
async def check_update():
    """检查 GitHub Releases 是否有新版本"""
    import urllib.request
    import json as _json

    current = "1.4.1"
    repo = "qinusui/ClipLingo"
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"

    try:
        req = urllib.request.Request(api_url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ClipLingo"
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode())

        tag = data.get("tag_name", "").lstrip("v")
        if not tag:
            return {"has_update": False, "current_version": current}

        def _ver_tuple(v: str):
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        if _ver_tuple(tag) > _ver_tuple(current):
            # 找到 exe 资产的下载链接
            download_url = None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name.endswith(".exe") or "setup" in name:
                    download_url = asset.get("browser_download_url")
                    break
            if not download_url:
                download_url = data.get("html_url", "")

            return {
                "has_update": True,
                "current_version": current,
                "latest_version": tag,
                "download_url": download_url,
                "release_notes": data.get("body", ""),
                "release_url": data.get("html_url", ""),
            }

        return {"has_update": False, "current_version": current}
    except Exception as e:
        logger.debug(f"更新检查失败（可忽略）: {e}")
        return {"has_update": False, "current_version": current, "error": str(e)}


def _open_browser():
    """延迟打开浏览器"""
    import webbrowser
    time.sleep(2)  # 等待服务器启动
    webbrowser.open('http://localhost:8000')


# PyInstaller 多进程支持：必须在顶层调用，子进程 __name__ == "__mp_main__" 依赖此调用
import multiprocessing
multiprocessing.freeze_support()

if __name__ == "__main__":
    # Docker 或 PyInstaller 中禁用 reload
    is_docker = os.environ.get('DOCKER_CONTAINER') == '1'

    if is_docker or is_frozen:
        # 打包模式下自动打开浏览器
        if is_frozen:
            threading.Thread(target=_open_browser, daemon=True).start()
        # 启动心跳监控线程
        threading.Thread(target=_heartbeat_monitor, daemon=True).start()
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    else:
        uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
