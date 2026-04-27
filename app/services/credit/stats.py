"""统计模块:管理后台积分消耗概览"""
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import now_utc
from app.models.user import User


class StatsMixin:
    """管理后台积分统计"""

    async def get_admin_stats(self, db: AsyncSession) -> dict:
        """管理后台:积分消耗统计概览"""
        from app.models.membership import CreditTransaction as CT

        total_used = await db.scalar(
            select(func.sum(func.abs(CT.amount))).where(CT.amount < 0)
        ) or 0

        total_granted = await db.scalar(
            select(func.sum(CT.amount)).where(CT.amount > 0)
        ) or 0

        today_start = datetime.combine(now_utc().date(), datetime.min.time())
        today_used = await db.scalar(
            select(func.sum(func.abs(CT.amount))).where(
                CT.amount < 0,
                CT.created_at >= today_start,
            )
        ) or 0

        type_stats_result = await db.execute(
            select(
                CT.type,
                func.count(CT.id).label("count"),
                func.sum(func.abs(CT.amount)).label("total"),
            )
            .where(CT.amount < 0)
            .group_by(CT.type)
        )
        type_stats = [
            {"type": r[0], "count": r[1], "total": r[2]}
            for r in type_stats_result.fetchall()
        ]

        active_users = await db.scalar(
            select(func.count(func.distinct(CT.user_id)))
        ) or 0
        total_users = await db.scalar(select(func.count(User.id))) or 0
        now_naive = now_utc().replace(tzinfo=None)
        active_vip_count = await db.scalar(
            select(func.count(User.id)).where(
                User.vip_level != "free",
                or_(User.vip_expire_at.is_(None), User.vip_expire_at > now_naive),
            )
        ) or 0

        return {
            "total_credits_consumed": total_used,
            "total_credits_granted": total_granted,
            "active_vip_count": active_vip_count,
            "total_users": total_users,
            "total_used": total_used,
            "total_granted": total_granted,
            "today_used": today_used,
            "active_users": active_users,
            "type_stats": type_stats,
        }
