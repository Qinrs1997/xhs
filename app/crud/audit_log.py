"""审计日志异步 CRUD"""
from datetime import datetime
from typing import Optional, Sequence, Tuple
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.audit_log import AuditLog, AuditLevel
from app.schemas.audit_log import AuditLogCreate, AuditLogQuery


class CRUDAuditLogAsync(CRUDBase[AuditLog, AuditLogCreate, AuditLogCreate]):
    """审计日志 CRUD"""

    async def query_logs(
        self,
        db: AsyncSession,
        *,
        query: AuditLogQuery,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[Sequence[AuditLog], int]:
        """
        查询审计日志

        支持多条件组合查询。
        """
        conditions = []

        if query.user_id is not None:
            conditions.append(AuditLog.user_id == query.user_id)
        if query.username:
            conditions.append(AuditLog.username.contains(query.username))
        if query.action:
            conditions.append(AuditLog.action == query.action)
        if query.level:
            conditions.append(AuditLog.level == query.level)
        if query.method:
            conditions.append(AuditLog.method == query.method)
        if query.path:
            conditions.append(AuditLog.path.contains(query.path))
        if query.success is not None:
            conditions.append(AuditLog.success == query.success)
        if query.start_time:
            conditions.append(AuditLog.created_at >= query.start_time)
        if query.end_time:
            conditions.append(AuditLog.created_at <= query.end_time)

        # 构建查询
        stmt = select(AuditLog)
        count_stmt = select(func.count()).select_from(AuditLog)

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        # 总数
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 分页和排序
        skip = (page - 1) * page_size
        stmt = stmt.order_by(desc(AuditLog.created_at)).offset(skip).limit(page_size)

        result = await db.execute(stmt)
        items = result.scalars().all()

        return items, total

    async def get_user_logs(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """获取指定用户的审计日志"""
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_action_logs(
        self,
        db: AsyncSession,
        *,
        action: str,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """获取指定操作类型的审计日志"""
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_high_level_logs(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """获取高敏感级别的审计日志"""
        stmt = (
            select(AuditLog)
            .where(AuditLog.level.in_([AuditLevel.HIGH.value, AuditLevel.CRITICAL.value]))
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_failed_logs(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """获取失败的操作日志"""
        stmt = (
            select(AuditLog)
            .where(AuditLog.success == False)  # noqa: E712
            .order_by(desc(AuditLog.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def count_by_action(
        self,
        db: AsyncSession,
        *,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> dict:
        """按操作类型统计"""
        stmt = select(
            AuditLog.action,
            func.count(AuditLog.id).label("count")
        ).group_by(AuditLog.action)

        if start_time:
            stmt = stmt.where(AuditLog.created_at >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.created_at <= end_time)

        result = await db.execute(stmt)
        return {row.action: row.count for row in result}

    async def count_by_user(
        self,
        db: AsyncSession,
        *,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10,
    ) -> list:
        """按用户统计操作次数（Top N）"""
        stmt = (
            select(
                AuditLog.user_id,
                AuditLog.username,
                func.count(AuditLog.id).label("count")
            )
            .where(AuditLog.user_id.isnot(None))
            .group_by(AuditLog.user_id, AuditLog.username)
            .order_by(desc("count"))
            .limit(limit)
        )

        if start_time:
            stmt = stmt.where(AuditLog.created_at >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.created_at <= end_time)

        result = await db.execute(stmt)
        return [
            {"user_id": row.user_id, "username": row.username, "count": row.count}
            for row in result
        ]


# 创建实例
audit_log_crud = CRUDAuditLogAsync(AuditLog)
