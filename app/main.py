"""FastAPI 应用入口（异步版本）"""
import asyncio
import sys
import mimetypes
from pathlib import Path

# Windows 系统可能缺少 .webp MIME 类型注册，导致 StaticFiles 返回 text/plain
mimetypes.add_type("image/webp", ".webp")

# 将项目根目录添加到 Python 路径（修复直接运行时的导入问题）
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

# FastAPI 0.135+ 原生用 Pydantic 直接序列化到 JSON bytes(比 ORJSONResponse 更快),
# 不再需要显式声明 default_response_class。如果未来需要自定义响应类,改这里。
_default_response_class = None

from app.core.config import settings
from app.core.database import (
    init_db,
    init_async_db,
    close_db,
    close_async_db,
)
from app.core.bootstrap import ensure_admin, ensure_ai_provider_async
from app.core.logger import logger
from app.core.exception_handlers import register_exception_handlers
from app.core.middleware import RequestTracingMiddleware, OperationLogMiddleware
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理 (纯异步)

    启动时：
    - 初始化数据库连接与基础检查
    - 异步初始化种子数据 (Admin, AI Providers)
    - 启动定时任务调度器
    - 初始化缓存
    """
    # ========== 启动时执行 ==========
    logger.info("=" * 60)
    logger.info("STARTUP: {} v{} 启动中...", settings.PROJECT_NAME, settings.VERSION)
    logger.info("ENV: {}", settings.APP_ENV.upper())
    logger.info("DEBUG_MODE: {}", 'ON' if settings.DEBUG else 'OFF')
    logger.info("ASYNC_MODE: ON")

    # 0. 多 worker + 无 Redis 的一致性警告
    # 幂等缓存已支持 Redis(启用时自动走 Redis),但限流/用户缓存仍为进程内。
    if settings.APP_WORKERS > 1 and not settings.REDIS_ENABLED:
        logger.warning(
            "检测到 APP_WORKERS={} 且 REDIS_ENABLED=False:"
            "限流/用户缓存为进程内,worker 间不共享,可能出现不一致行为。"
            "生产建议开启 REDIS_ENABLED=True。",
            settings.APP_WORKERS,
        )

    # 1. 数据库初始化检查
    # init_db() 内部会执行同步连通性检测 + 自动建库 + alembic upgrade head,
    # 属于可能长耗时的阻塞 I/O,必须放到线程池执行,避免阻塞 ASGI 事件循环。
    await asyncio.to_thread(init_db)
    await init_async_db()

    # 2. 异步种子数据初始化
    from app.core.database import get_async_db_context
    async with get_async_db_context() as db:
        await ensure_admin(db)

    await ensure_ai_provider_async()

    # 2.5 TOML → DB 配置同步（确保 DB 中的模型列表与 TOML 一致）
    try:
        from app.ai.services.config_sync import config_sync_service
        sync_result = await config_sync_service.sync_toml_to_db()
        logger.info("TOML→DB sync: {}", sync_result)
    except Exception as e:
        logger.warning("TOML→DB 配置同步失败（不影响启动）: {}", e)

    # 3. 启动定时任务调度器
    try:
        from app.core.tasks import start_scheduler
        await start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.warning("Scheduler startup failed: {}", e)

    logger.info("Startup complete")
    logger.info("=" * 60)

    yield

    # ========== 关闭时执行 ==========
    logger.info("=" * 60)
    logger.info("Application shutting down...")

    # 关闭定时任务调度器
    try:
        from app.core.tasks import stop_scheduler
        await stop_scheduler()
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.warning("Scheduler shutdown error: {}", e)

    # 关闭缓存连接
    try:
        from app.core.cache import cache
        await cache.close()
        logger.info("Cache closed")
    except Exception as e:
        logger.warning("Cache shutdown error: {}", e)

    # 关闭 AI 服务
    try:
        from app.ai.facade import ai
        if ai.is_initialized:
            await ai.close()
            logger.info("AI service closed")
    except ImportError:
        pass

    # 关闭图片处理器
    try:
        from app.core.image_processor import image_processor
        await image_processor.close()
        logger.info("Image processor closed")
    except ImportError:
        pass

    # 关闭共享 HTTP 客户端
    try:
        from app.core.http_client import close_http_client
        await close_http_client()
        logger.info("Shared HTTP client closed")
    except ImportError:
        pass

    await close_async_db()
    close_db()

    logger.info("Application closed")
    logger.info("=" * 60)


# OpenAPI 分组标签说明（Swagger UI 中每个模块的描述）
openapi_tags = [
    {"name": "健康检查", "description": "应用存活/就绪探针，数据库和依赖状态"},
    {"name": "认证", "description": "登录、登出、Token 刷新、密码重置"},
    {"name": "用户管理", "description": "用户 CRUD、头像上传、角色绑定"},
    {"name": "用户偏好设置", "description": "用户个人偏好配置"},
    {"name": "角色管理", "description": "角色 CRUD、权限分配"},
    {"name": "部门管理", "description": "组织架构树、部门 CRUD"},
    {"name": "审计日志", "description": "敏感操作记录查询、统计"},
    {"name": "公告管理", "description": "系统公告发布、查询"},
    {"name": "上传接口", "description": "文件上传、静态资源管理"},
    {"name": "定时任务管理", "description": "任务调度配置、执行日志、暂停/恢复"},
    {"name": "邮件服务", "description": "邮件发送、模板管理"},
    {"name": "AI 服务", "description": "AI 对话、图像生成、模型管理"},
    {"name": "AI 提示词管理", "description": "Prompt 模板 CRUD"},
    {"name": "AI 管理 (管理员)", "description": "AI 提供商配置、模型管理"},
]

_app_kwargs = dict(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    openapi_url=settings.OPENAPI_URL,
    openapi_tags=openapi_tags,
)
if _default_response_class:
    _app_kwargs["default_response_class"] = _default_response_class
app = FastAPI(**_app_kwargs)


# ==================== 中间件配置 ====================
# 注意：中间件的执行顺序是添加顺序的**逆序**
# 即最后添加的中间件最先执行（最外层），最先添加的最后执行（最内层，靠近 App）

# 0. 响应包装中间件（最内层，最靠近 App，处理原始响应）
from app.core.middleware import ResponseNormalizationMiddleware
app.add_middleware(ResponseNormalizationMiddleware)

# 0.5 Prometheus 监控中间件（在响应包装之后，记录真实响应状态）
if settings.METRICS_ENABLED:
    from app.core.metrics import setup_metrics
    setup_metrics(app)

# 1. CORS 中间件
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=settings.CORS_ALLOW_METHODS,
        allow_headers=settings.CORS_ALLOW_HEADERS,
        max_age=settings.CORS_MAX_AGE,
    )

# 1.5 Trusted Host 中间件(防 Host 头投毒/缓存投毒)
# 生产必须在 ALLOWED_HOSTS 中列出真实域名;默认 ["*"] 仅开发,生产会放行任何 Host
if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["*"]:
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# 1.6 安全响应头中间件(HSTS/X-Frame-Options/X-Content-Type-Options/Referrer-Policy)
if settings.SECURITY_HEADERS_ENABLED:
    from app.core.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

# 2. 速率限制中间件(可选,根据配置启用)
if settings.RATE_LIMIT_ENABLED:
    from app.core.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)

# 3. 幂等性保护中间件(防止写操作重复执行)
from app.core.idempotency import IdempotencyMiddleware
app.add_middleware(IdempotencyMiddleware)

# 4. 操作日志中间件(记录写操作)
app.add_middleware(OperationLogMiddleware)

# 5. GZip 压缩(> 500 字节的响应自动压缩)
app.add_middleware(GZipMiddleware, minimum_size=500)

# 6. 请求追踪中间件(最后添加,最先执行)
app.add_middleware(RequestTracingMiddleware)



# ==================== 异常处理器 ====================
register_exception_handlers(app)


# ==================== 健康检查 ====================
from app.core.health import router as health_router, include_detailed_health_if_available
app.include_router(health_router)
# /health/detail 独立挂载(依赖 api.deps.get_current_superuser,放在主路由后避免循环 import)
include_detailed_health_if_available(app)


# ==================== API 路由 ====================
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# ==================== 静态文件挂载 ====================
# 确保上传目录存在
uploads_path = Path(settings.UPLOAD_DIR)
if not uploads_path.exists():
    uploads_path.mkdir(parents=True, exist_ok=True)

app.mount(f"/{settings.UPLOAD_DIR.rstrip('/')}", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


# ==================== 直接运行 ====================
if __name__ == "__main__":
    import uvicorn

    # 所有配置从 settings 读取，不再硬编码！
    logger.info("=" * 60)
    logger.info("Direct startup mode")
    logger.info("ENV: {}", settings.APP_ENV)
    logger.info("ADDRESS: {}:{}", settings.APP_HOST, settings.APP_PORT)
    logger.info("WORKERS: {}", settings.APP_WORKERS)
    logger.info("ASYNC_MODE: ON")
    logger.info("REQUEST_TRACING: ON")
    logger.info("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        workers=settings.APP_WORKERS if not settings.DEBUG else 1
    )
