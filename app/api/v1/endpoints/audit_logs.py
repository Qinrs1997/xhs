"""审计日志查询 API

仅管理员可查询，用于安全审计和合规。
"""
from typing import Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.api.deps import get_current_superuser
from app.crud import audit_log_crud
from app.schemas import Response
from app.schemas.audit_log import AuditLogResponse, AuditLogList, AuditLogQuery
from app.models.user import User as UserModel

router = APIRouter()


@router.get(
    "",
    response_model=Response[AuditLogList],
    summary="查询审计日志",
)
async def list_audit_logs(
    db: AsyncSession = Depends(get_async_db),
    user_id: Optional[int] = Query(None, description="用户ID"),
    username: Optional[str] = Query(None, description="用户名"),
    action: Optional[str] = Query(None, description="操作类型"),
    level: Optional[str] = Query(None, description="敏感级别"),
    method: Optional[str] = Query(None, description="HTTP方法"),
    path: Optional[str] = Query(None, description="请求路径"),
    success: Optional[bool] = Query(None, description="是否成功"),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """
    查询审计日志（仅超级用户）

    支持多条件组合查询。
    """
    query = AuditLogQuery(
        user_id=user_id,
        username=username,
        action=action,
        level=level,
        method=method,
        path=path,
        success=success,
        start_time=start_time,
        end_time=end_time,
    )

    logs, total = await audit_log_crud.query_logs(
        db, query=query, page=page, page_size=page_size
    )

    return Response(
        code=200,
        message="查询成功",
        data=AuditLogList(total=total, items=list(logs))
    )


@router.get(
    "/user/{user_id}",
    response_model=Response[list[AuditLogResponse]],
    summary="获取用户操作日志",
)
async def get_user_logs(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """获取指定用户的操作日志（仅超级用户）"""
    logs = await audit_log_crud.get_user_logs(
        db, user_id=user_id, skip=skip, limit=limit
    )
    return Response(code=200, message="查询成功", data=list(logs))


@router.get(
    "/high-level",
    response_model=Response[list[AuditLogResponse]],
    summary="获取高敏感操作日志",
)
async def get_high_level_logs(
    db: AsyncSession = Depends(get_async_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """获取高敏感级别的操作日志（仅超级用户）"""
    logs = await audit_log_crud.get_high_level_logs(db, skip=skip, limit=limit)
    return Response(code=200, message="查询成功", data=list(logs))


@router.get(
    "/failed",
    response_model=Response[list[AuditLogResponse]],
    summary="获取失败操作日志",
)
async def get_failed_logs(
    db: AsyncSession = Depends(get_async_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """获取失败的操作日志（仅超级用户）"""
    logs = await audit_log_crud.get_failed_logs(db, skip=skip, limit=limit)
    return Response(code=200, message="查询成功", data=list(logs))


@router.get(
    "/stats/action",
    response_model=Response[dict],
    summary="按操作类型统计",
)
async def get_stats_by_action(
    db: AsyncSession = Depends(get_async_db),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """按操作类型统计（仅超级用户）"""
    stats = await audit_log_crud.count_by_action(
        db, start_time=start_time, end_time=end_time
    )
    return Response(code=200, message="统计成功", data=stats)


@router.get(
    "/stats/user",
    response_model=Response[list],
    summary="按用户统计（Top N）",
)
async def get_stats_by_user(
    db: AsyncSession = Depends(get_async_db),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    limit: int = Query(10, ge=1, le=50, description="Top N"),
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """按用户统计操作次数（仅超级用户）"""
    stats = await audit_log_crud.count_by_user(
        db, start_time=start_time, end_time=end_time, limit=limit
    )
    return Response(code=200, message="统计成功", data=stats)
