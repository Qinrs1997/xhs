"""统一异常处理器

在 FastAPI 应用中注册这些处理器，实现统一的错误响应格式。
使用方法：
    from app.core.exception_handlers import register_exception_handlers
    register_exception_handlers(app)
"""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import AppException
from app.core.config import settings
from app.core.logger import logger


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """处理自定义业务异常"""
    logger.warning(
        "业务异常 | path={} method={} code={} message={}",
        request.url.path, request.method, exc.code, exc.message,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """处理 HTTP 异常"""
    logger.warning(
        "HTTP异常 | path={} method={} status={} detail={}",
        request.url.path, request.method, exc.status_code, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "error_code": "HTTP_ERROR",
            "message": exc.detail or "请求错误",
        },
    )


# 日志中默认脱敏的字段名(命中子串即脱敏,大小写不敏感)
_SENSITIVE_LOC_KEYS: tuple[str, ...] = (
    "password", "pwd", "secret", "token", "api_key",
    "apikey", "access_key", "access_token", "refresh_token",
    "authorization", "cookie", "session", "credit", "card",
)


def _is_sensitive_loc(loc_parts: list[str] | tuple) -> bool:
    """判断 loc 路径是否命中敏感字段"""
    joined = ".".join(str(p) for p in loc_parts).lower()
    return any(k in joined for k in _SENSITIVE_LOC_KEYS)


def _sanitize_validation_errors(errors: list[dict]) -> list[dict]:
    """精简 + 脱敏 validation errors,仅保留日志所需的最小信息。

    - `input` 字段对敏感 loc 强制改成 "***";非敏感 loc 截断到前 64 字符
    - `ctx` 中的 `error`/`exception` 对象按长度截断为字符串,避免栈对象入日志
    - 丢弃 `url`(pydantic 文档链接),对日志无意义且占用篇幅
    """
    sanitized: list[dict] = []
    for err in errors:
        loc = err.get("loc") or ()
        item: dict = {
            "loc": loc,
            "type": err.get("type"),
            "msg": err.get("msg"),
        }
        raw_input = err.get("input")
        if raw_input is not None:
            if _is_sensitive_loc(loc):
                item["input"] = "***"
            else:
                text = str(raw_input)
                item["input"] = text if len(text) <= 64 else text[:64] + "…"
        ctx = err.get("ctx")
        if ctx:
            trimmed: dict = {}
            for k, v in ctx.items():
                text = str(v)
                trimmed[k] = text if len(text) <= 120 else text[:120] + "…"
            item["ctx"] = trimmed
        sanitized.append(item)
    return sanitized


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """处理请求参数验证异常"""
    errors = exc.errors()
    logger.warning(
        "参数验证失败 | path={} method={} errors={}",
        request.url.path, request.method, _sanitize_validation_errors(errors),
    )
    error_messages = []
    for error in errors:
        loc = ".".join(str(x) for x in error.get("loc", []))
        msg = error.get("msg", "验证失败")
        error_messages.append(f"{loc}: {msg}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 422,
            "error_code": "VALIDATION_ERROR",
            "message": "请求参数验证失败",
            "detail": error_messages,
        },
    )


async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """处理数据库异常"""
    logger.error(
        "数据库异常 | path={} method={} error={}",
        request.url.path, request.method, exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "error_code": "DATABASE_ERROR",
            "message": "数据库操作失败",
            "detail": str(exc) if settings.DEBUG else None,
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """处理未捕获的异常"""
    logger.exception(
        "未处理异常 | path={} method={} error={}",
        request.url.path, request.method, exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "error_code": "INTERNAL_ERROR",
            "message": "服务器内部错误",
            "detail": str(exc) if settings.DEBUG else None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    注册所有异常处理器

    Args:
        app: FastAPI 应用实例
    """
    # 自定义业务异常
    app.add_exception_handler(AppException, app_exception_handler)

    # HTTP 异常
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # 参数验证异常
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # 数据库异常
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)

    # 全局兜底异常
    app.add_exception_handler(Exception, global_exception_handler)
