# 第一阶段：构建前端
FROM node:18-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# 第二阶段：后端 + 前端静态文件
FROM python:3.11-slim

# 安装系统依赖（使用阿里云镜像加速）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg || \
    apt-get install -y --no-install-recommends --fix-missing ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制 Python 依赖文件
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制后端依赖
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# 复制后端代码
COPY backend/ ./backend/

# 复制核心模块
COPY core/ ./core/
COPY main.py ./

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# 创建输出目录和日志目录
RUN mkdir -p /app/output /app/temp /app/logs

# 暴露端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV DOCKER_CONTAINER=1

# 启动后端
CMD ["python", "backend/main.py"]
