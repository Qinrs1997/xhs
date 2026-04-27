# ============================================================
# XHS Backend — FastAPI 生产镜像
# ============================================================
# 构建:
#   docker build -t xhs-backend:latest ./backend
# 运行（需挂载 .env）:
#   docker run --rm -p 8999:8999 --env-file .env xhs-backend:latest
# ============================================================

FROM python:3.11-slim AS base

# 系统级 UTF-8 + 不缓冲输出 + 不生成 pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# ------------------------------------------------------------
# 1) 系统依赖（MySQL 客户端 + 图像处理 + curl 健康检查）
# ------------------------------------------------------------
# libmariadb-dev: asyncmy/pymysql 需要
# libjpeg-turbo0-progs + zlib1g: Pillow 运行时需要
# curl: HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libmariadb-dev \
        libjpeg62-turbo \
        zlib1g \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# 2) Python 依赖（先拷贝 requirements 以利用 Docker 层缓存）
# ------------------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------
# 3) 应用代码
# ------------------------------------------------------------
COPY . ./

# 确保日志与上传目录存在（容器内）
RUN mkdir -p /app/logs /app/uploads

# ------------------------------------------------------------
# 4) 非 root 用户（容器安全最佳实践）
# ------------------------------------------------------------
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

# ------------------------------------------------------------
# 5) 健康检查（对齐 /health/live，和 systemd service 一致）
# ------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8999/health/live || exit 1

EXPOSE 8999

# ------------------------------------------------------------
# 6) 启动命令
# ------------------------------------------------------------
# workers 数量根据 CPU 调整；生产多进程建议 2-4
# 使用 shell form 让环境变量展开：
# - UVICORN_WORKERS       默认 2,生产可按 CPU 调整
# - FORWARDED_ALLOW_IPS   默认仅信任本地/容器网段(172.16.0.0/12 覆盖 docker 默认 bridge)
#                         有可信反代时可设为反代 IP CIDR;不能无条件 * 以免伪造 X-Forwarded-For
# - PROXY_HEADERS_FLAG    默认开启;无反代场景可设为 "" 关闭
ENV UVICORN_WORKERS=2 \
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,172.16.0.0/12" \
    PROXY_HEADERS_FLAG=--proxy-headers

CMD uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8999 \
    --workers ${UVICORN_WORKERS} \
    ${PROXY_HEADERS_FLAG} \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS}" \
    --access-log
