FROM python:3.12-slim

# 设置环境变量，防止 Python 写入 pyc 文件和缓冲 stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 安装必要的系统运行时依赖（如果需要，比如编译工具。因为使用纯 Python 驱动 PyMySQL，此处保持精简）
# RUN apt-get update && apt-get install -y --no-install-recommends gcc libc-dev && rm -rf /var/lib/apt/lists/*

# 复制依赖定义文件
COPY requirements.txt /app/

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目代码
COPY . /app/

# 设置工作目录至 Django 项目根目录（manage.py 所在目录）
WORKDIR /app/automake

# 默认启动命令：启动 Celery Worker，应用为 default
CMD ["celery", "-A", "default", "worker", "--loglevel=info"]
