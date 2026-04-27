"""审计日志模块

提供选择性记录敏感操作到数据库的功能。

使用方式：

1. 依赖注入（推荐 - 可获取更多信息）：
    from app.core.audit import AuditLogger, AuditAction

    @router.delete("/users/{user_id}")
    async def delete_user(
        user_id: int,
        db: AsyncSession = Depends(get_async_db),
        audit: AuditLogger = Depends(get_audit_logger(
            action=AuditAction.USER_DELETE,
            description="删除用户"
        ))
    ):
        # ... 业务逻辑 ...
        await audit.log(detail={"target_user_id": user_id})
        return Response(message="删除成功")

2. 装饰器（简单场景）：
    from app.core.audit import audit_log, AuditAction

    @router.post("/payment")
    @audit_log(action=AuditAction.PAYMENT, description="用户支付")
    async def payment(...):
        ...
"""
import asyncio
import functools
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# 持有 fire-and-forget 的 audit task 强引用，避免事件循环 GC 提前终止它们
# set 在任务完成后自动 discard 自己，长时间运行也不会膨胀
_audit_background_tasks: set[asyncio.Task] = set()

from fastapi import Request

from app.core.context import get_request_id, get_current_user_id, get_current_user_name
from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditAction, AuditLevel

from app.core.logger import logger

# 操作类型对应的默认敏感级别
ACTION_LEVEL_MAP = {
    # 低敏感
    AuditAction.USER_LOGIN: AuditLevel.LOW,
    AuditAction.USER_LOGOUT: AuditLevel.LOW,
    AuditAction.SENSITIVE_VIEW: AuditLevel.LOW,

    # 中敏感
    AuditAction.USER_REGISTER: AuditLevel.MEDIUM,
    AuditAction.USER_UPDATE: AuditLevel.MEDIUM,
    AuditAction.DATA_EXPORT: AuditLevel.MEDIUM,
    AuditAction.DATA_IMPORT: AuditLevel.MEDIUM,
    AuditAction.ROLE_CREATE: AuditLevel.MEDIUM,

    # 高敏感
    AuditAction.DEPARTMENT_CREATE: AuditLevel.HIGH,
    AuditAction.DEPARTMENT_UPDATE: AuditLevel.HIGH,
    AuditAction.DEPARTMENT_DELETE: AuditLevel.HIGH,
    AuditAction.DEPARTMENT_USER_ASSIGN: AuditLevel.HIGH,
    AuditAction.DEPARTMENT_USER_REMOVE: AuditLevel.HIGH,

    AuditAction.USER_DELETE: AuditLevel.HIGH,
    AuditAction.PASSWORD_CHANGE: AuditLevel.HIGH,
    AuditAction.PASSWORD_RESET: AuditLevel.HIGH,
    AuditAction.ROLE_DELETE: AuditLevel.HIGH,
    AuditAction.ROLE_ASSIGN: AuditLevel.HIGH,
    AuditAction.ROLE_REMOVE: AuditLevel.HIGH,
    AuditAction.PERMISSION_CHANGE: AuditLevel.HIGH,
    AuditAction.DATA_DELETE: AuditLevel.HIGH,
    AuditAction.CONFIG_CHANGE: AuditLevel.HIGH,
    AuditAction.SYSTEM_SETTING: AuditLevel.HIGH,

    # 极高敏感
    AuditAction.PAYMENT: AuditLevel.CRITICAL,
    AuditAction.REFUND: AuditLevel.CRITICAL,
    AuditAction.WITHDRAW: AuditLevel.CRITICAL,
    AuditAction.RECHARGE: AuditLevel.CRITICAL,
    AuditAction.TRANSFER: AuditLevel.CRITICAL,
}


@dataclass
class AuditLogger:
    """
    审计日志记录器

    在 API 端点中使用，记录敏感操作到数据库。
    """
    request: Request
    action: AuditAction
    description: Optional[str] = None
    level: Optional[AuditLevel] = None
    _start_time: float = field(default_factory=time.time)
    _logged: bool = False

    async def log(
        self,
        *,
        detail: Optional[dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """
        记录审计日志

        Args:
            detail: 操作详情（会转为 JSON 存储）
            success: 操作是否成功
            error_message: 错误信息（失败时）
        """
        if self._logged:
            return
        self._logged = True

        # 异步写入数据库（不阻塞主请求）
        task = asyncio.create_task(
            self._write_log(
                detail=detail,
                success=success,
                error_message=error_message,
            )
        )
        _audit_background_tasks.add(task)
        task.add_done_callback(_audit_background_tasks.discard)

    async def _write_log(
        self,
        *,
        detail: Optional[dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """实际写入数据库"""
        try:
            from app.crud.audit_log import audit_log_crud
            from app.schemas.audit_log import AuditLogCreate

            # 计算响应时间
            response_time = (time.time() - self._start_time) * 1000

            # 获取请求信息
            request_id = get_request_id() or "-"
            user_id = get_current_user_id()
            username = get_current_user_name()

            # 确定敏感级别
            level = self.level or ACTION_LEVEL_MAP.get(self.action, AuditLevel.MEDIUM)

            # 构建日志数据
            log_data = AuditLogCreate(
                request_id=request_id,
                user_id=user_id,
                username=username,
                action=self.action.value,
                level=level.value,
                description=self.description,
                method=self.request.method,
                path=str(self.request.url.path),
                ip=self._get_client_ip(),
                user_agent=self.request.headers.get("user-agent", "")[:500],
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                response_time=response_time,
                success=success,
                error_message=error_message,
            )

            # 使用独立会话写入
            async with AsyncSessionLocal() as db:
                await audit_log_crud.create(db, obj_in=log_data)
                await db.commit()

            logger.debug(
                "[Audit] {} | {} | user={} | success={}",
                self.action.value,
                self.request.url.path,
                user_id,
                success,
            )

        except Exception as e:
            logger.error("[Audit] 审计日志写入失败: {}", str(e))

    def _get_client_ip(self) -> str:
        """获取客户端 IP"""
        from app.core.utils import get_client_ip
        return get_client_ip(self.request)


def get_audit_logger(
    action: AuditAction,
    description: Optional[str] = None,
    level: Optional[AuditLevel] = None,
) -> Callable:
    """
    获取审计日志记录器（依赖注入）

    使用示例：
        @router.delete("/users/{user_id}")
        async def delete_user(
            user_id: int,
            audit: AuditLogger = Depends(get_audit_logger(
                action=AuditAction.USER_DELETE,
                description="删除用户"
            ))
        ):
            # ... 业务逻辑 ...
            await audit.log(detail={"target_user_id": user_id})
    """
    def dependency(request: Request) -> AuditLogger:
        return AuditLogger(
            request=request,
            action=action,
            description=description,
            level=level,
        )
    return dependency


def audit_log(
    action: AuditAction,
    description: Optional[str] = None,
    level: Optional[AuditLevel] = None,
) -> Callable:
    """
    审计日志装饰器

    自动记录函数执行结果，无需手动调用 log()。
    适用于简单场景，不需要自定义详情的情况。

    使用示例：
        @router.post("/payment")
        @audit_log(action=AuditAction.PAYMENT, description="用户支付")
        async def payment(request: Request, ...):
            return {"success": True}

    注意：使用装饰器时，函数必须有 request 参数。
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取 request 对象
            request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                logger.warning("[Audit] 装饰器需要 request 参数")
                return await func(*args, **kwargs)

            audit_logger = AuditLogger(
                request=request,
                action=action,
                description=description,
                level=level,
            )

            try:
                result = await func(*args, **kwargs)
                await audit_logger.log(success=True)
                return result
            except Exception as e:
                await audit_logger.log(success=False, error_message=str(e))
                raise

        return wrapper
    return decorator


# 导出
__all__ = [
    "AuditAction",
    "AuditLevel",
    "AuditLogger",
    "audit_log",
    "get_audit_logger",
]
