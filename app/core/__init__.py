"""核心模块

提供同步和异步两套数据库操作：
- 异步（推荐）：用于 API 请求处理
- 同步：用于 Alembic 迁移和启动初始化

还提供：
- 请求上下文（请求 ID、用户信息）
- 统一日志
- 自定义异常
- 中间件
- 速率限制
- 缓存
- 定时任务调度
"""
from app.core.config import settings
from app.core.database import (
    # 异步（推荐）
    get_async_db,
    get_async_db_context,
    async_engine,
    AsyncSessionLocal,
    init_async_db,
    close_async_db,
    # 同步（仅限 Alembic/启动初始化）
    init_db,
    close_db,
)
from app.models.base import Base  # Base 类从 models.base 导入
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    verify_token
)
from app.core.logger import logger, get_logger
from app.core.context import (
    get_request_id,
    set_request_id,
    get_current_user_id,
    get_current_user_name,
    set_current_user,
)
from app.core.exceptions import (
    AppException,
    BadRequestError,
    ValidationError,
    AuthenticationError,
    InvalidTokenError,
    TokenExpiredError,
    PermissionDeniedError,
    NotFoundError,
    ConflictError,
    DuplicateError,
    InternalError,
    DatabaseError,
)
from app.core.rate_limit import (
    rate_limit,
    rate_limit_decorator,
    RateLimitMiddleware,
    get_rate_limiter,
)

__all__ = [
    # 异常
    "AppException",
    "AsyncSessionLocal",
    "AuthenticationError",
    "BadRequestError",
    "Base",
    "ConflictError",
    "DatabaseError",
    "DuplicateError",
    "InternalError",
    "InvalidTokenError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitMiddleware",
    "TokenExpiredError",
    "ValidationError",
    "async_engine",
    "close_async_db",
    "close_db",
    "create_access_token",
    # 数据库 - 异步（推荐）
    "get_async_db",
    "get_async_db_context",
    "get_current_user_id",
    "get_current_user_name",
    "get_logger",
    "get_password_hash",
    "get_rate_limiter",
    # 请求上下文
    "get_request_id",
    "init_async_db",
    # 数据库 - 同步（仅限 Alembic）
    "init_db",
    # 日志
    "logger",
    # 速率限制
    "rate_limit",
    "rate_limit_decorator",
    "set_current_user",
    "set_request_id",
    # 配置
    "settings",
    # 安全
    "verify_password",
    "verify_token",
]
