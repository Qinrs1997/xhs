"""XHS 任务统计端点

接口列表:
- GET /tasks/stats   任务统计(含 7 天趋势 + 成功率)
- GET /stats         兼容别名,等同 /tasks/stats(标记 deprecated)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_async_db
from app.models.user import User
from app.schemas.response import Response

from ._shared import _build_enhanced_stats

router = APIRouter()


@router.get(
    "/tasks/stats",
    response_model=Response[dict],
    summary="获取任务统计",
    description="获取当前用户的任务统计(含 7 天趋势、成功率)。",
)
async def get_task_stats(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """获取增强版任务统计"""
    stats = await _build_enhanced_stats(db, current_user.id)
    return Response(code=200, success=True, message="获取成功", data=stats)


@router.get(
    "/stats",
    response_model=Response[dict],
    summary="生成统计数据(兼容路径)",
    description="等同于 GET /tasks/stats,为前端兼容保留。请迁移到 /tasks/stats。",
    deprecated=True,
)
async def stats_alias(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """统计数据(别名,复用共享逻辑)"""
    stats = await _build_enhanced_stats(db, current_user.id)
    return Response(code=200, success=True, message="获取成功", data=stats)
