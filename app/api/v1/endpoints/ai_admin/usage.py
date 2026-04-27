"""AI 用量统计接口

GET /usage/stats        —— 最近 N 天总量统计
GET /usage/by-model     —— 按模型分组统计
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superuser
from app.core.database import get_async_db
from app.core.timezone import now_utc
from app.models.ai import AIUsageLog
from app.models.user import User
from app.schemas.ai_admin import UsageStatsResponse

router = APIRouter()


@router.get(
    "/usage/stats",
    response_model=UsageStatsResponse,
    summary="获取 AI 用量统计",
)
async def get_usage_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """获取最近 N 天的 AI 用量统计"""
    since = now_utc().replace(tzinfo=None) - timedelta(days=days)

    result = await db.execute(
        select(
            func.count(AIUsageLog.id).label("total"),
            func.sum(AIUsageLog.total_tokens).label("tokens"),
            func.sum(AIUsageLog.prompt_tokens).label("prompt"),
            func.sum(AIUsageLog.completion_tokens).label("completion"),
            func.avg(AIUsageLog.latency_ms).label("avg_latency"),
            func.sum(func.cast(AIUsageLog.success, Integer)).label("success_count"),
        ).where(AIUsageLog.created_at >= since)
    )
    row = result.one()

    total = row.total or 0
    success = row.success_count or 0

    return UsageStatsResponse(
        total_requests=total,
        total_tokens=row.tokens or 0,
        total_prompt_tokens=row.prompt or 0,
        total_completion_tokens=row.completion or 0,
        success_rate=round(success / total * 100, 2) if total > 0 else 100.0,
        avg_latency_ms=round(row.avg_latency or 0, 2),
    )


@router.get("/usage/by-model", summary="按模型统计用量")
async def get_usage_by_model(
    days: int = 30,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """按模型分组统计用量"""
    since = now_utc().replace(tzinfo=None) - timedelta(days=days)

    result = await db.execute(
        select(
            AIUsageLog.model,
            func.count(AIUsageLog.id).label("requests"),
            func.sum(AIUsageLog.total_tokens).label("tokens"),
        )
        .where(AIUsageLog.created_at >= since)
        .group_by(AIUsageLog.model)
        .order_by(func.sum(AIUsageLog.total_tokens).desc())
    )

    return [
        {"model": row.model, "requests": row.requests, "tokens": row.tokens or 0}
        for row in result.all()
    ]
