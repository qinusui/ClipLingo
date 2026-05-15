"""
一键启动后端和前端服务 — 关闭浏览器页面后自动停止所有服务
"""

import subprocess
import sys
import os
import json
import time
import webbrowser
from pathlib import Path


def main():
    print("=" * 50)
    print("ClipLingo - 一键启动")
    print("=" * 50)

    # 从 scripts/ 目录向上找到项目根目录
    root_dir = Path(__file__).parent.parent
    backend_dir = root_dir / 'backend'
    frontend_dir = root_dir / 'frontend'

    # 检查前端依赖
    if not (frontend_dir / 'node_modules').exists():
        print("\n前端依赖未安装，正在安装...")
        subprocess.run(['npm', 'install'], cwd=frontend_dir, shell=True, check=True)
        print("前端依赖安装完成")

    processes = []
    pid_file = backend_dir / 'pids.json'
    port_file = root_dir / ".port"

    try:
        # 启动后端
        print("正在启动后端...")
        try:
            backend_process = subprocess.Popen(
                [sys.executable, 'main.py'],
                cwd=backend_dir,
            )
            processes.append(backend_process)
            print(f"  后端 PID: {backend_process.pid}")
        except Exception as e:
            print(f"  后端启动失败: {e}")
            sys.exit(1)

        # 等待后端写入 .port 文件
        backend_port = "8000"
        for _ in range(50):
            if port_file.exists():
                backend_port = port_file.read_text().strip()
                break
            time.sleep(0.1)
        else:
            print("  警告: 后端未写入 .port 文件，使用默认端口 8000")

        print(f"\n后端: http://localhost:{backend_port}")
        print(f"前端: http://localhost:5173")
        print("\n关闭浏览器页面后 5 秒自动停止所有服务")
        print("按 Ctrl+C 可手动停止")
        print("-" * 50)

        # 启动前端，传递后端端口给 Vite
        print("正在启动前端...")
        try:
            frontend_env = {**os.environ, 'BACKEND_PORT': backend_port}
            frontend_process = subprocess.Popen(
                'npm run dev',
                cwd=frontend_dir,
                shell=True,
                env=frontend_env,
            )
            processes.append(frontend_process)
            print(f"  前端 PID: {frontend_process.pid}")
        except Exception as e:
            print(f"  前端启动失败: {e}")
            backend_process.terminate()
            sys.exit(1)

        # 写入 PID 文件供后端自动停服使用
        pid_data = {
            'backend_pid': backend_process.pid,
            'frontend_pid': frontend_process.pid,
            'orchestrator_pid': os.getpid()
        }
        pid_file.write_text(json.dumps(pid_data))

        # 等待后端启动后自动打开浏览器
        print("等待服务就绪...")
        time.sleep(3)
        webbrowser.open(f'http://localhost:5173')
        print("浏览器已打开")

        # 监控进程状态
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f"\n进程退出 (code={p.returncode})，正在停止所有服务...")
                    for proc in processes:
                        if proc.poll() is None:
                            proc.terminate()
                    pid_file.unlink(missing_ok=True)
                    sys.exit(1)
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n正在停止服务...")
    except Exception as e:
        print(f"\n启动失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        pid_file.unlink(missing_ok=True)
        # 清理 port 文件
        port_file.unlink(missing_ok=True)
        print("所有服务已停止")


if __name__ == "__main__":
    main()
