"""软删除 CRUD 操作基类（继承 CRUDBase）

为继承 SoftDeleteModel 的模型提供软删除支持。
通过继承 CRUDBase 并 override 相关方法加入 is_deleted 过滤，
避免代码重复。

使用示例：
    from app.crud.base_soft_delete import CRUDBaseSoftDelete

    class CRUDArticle(CRUDBaseSoftDelete[Article, ArticleCreate, ArticleUpdate]):
        pass

    article_crud = CRUDArticle(Article)
"""
from datetime import datetime, timezone
from typing import TypeVar, Optional, Any, Dict, Tuple, List, Sequence
from pydantic import BaseModel
from sqlalchemy import select, func, asc, desc, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import SoftDeleteModel
from app.crud.base import CRUDBase

ModelType = TypeVar("ModelType", bound=SoftDeleteModel)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBaseSoftDelete(CRUDBase[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    软删除异步 CRUD 基类（继承 CRUDBase）

    特点：
    - 默认查询自动过滤已删除记录
    - delete 方法执行软删除（标记 is_deleted=True）
    - 提供 hard_delete 方法进行物理删除
    - 提供 restore / restore_multi 方法恢复已删除记录
    - 提供 get_deleted / count_deleted 方法查询已删除记录
    """

    # ==================== Override 查询方法（加入 is_deleted 过滤） ====================

    async def get(
        self, db: AsyncSession, id: int, include_deleted: bool = False
    ) -> Optional[ModelType]:
        """根据 ID 获取单条记录（默认排除已删除）"""
        query = select(self.model).where(self.model.id == id)
        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_ids(
        self, db: AsyncSession, ids: List[int], include_deleted: bool = False
    ) -> Sequence[ModelType]:
        """根据 ID 列表批量获取记录（默认排除已删除）"""
        if not ids:
            return []
        query = select(self.model).where(self.model.id.in_(ids))
        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        result = await db.execute(query)
        return result.scalars().all()

    async def get_multi(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        order_desc: bool = False,
        include_deleted: bool = False,
    ) -> Sequence[ModelType]:
        """获取多条记录（默认排除已删除）"""
        query = select(self.model)
        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712

        if order_by and hasattr(self.model, order_by):
            order_column = getattr(self.model, order_by)
            query = query.order_by(desc(order_column) if order_desc else asc(order_column))

        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_multi_paginated(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        order_desc: bool = False,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
    ) -> Tuple[Sequence[ModelType], int]:
        """分页获取记录（默认排除已删除）"""
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)

        # 默认过滤已删除
        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
            count_query = count_query.where(self.model.is_deleted == False)  # noqa: E712

        # 应用过滤条件
        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field) and value is not None:
                    query = query.where(getattr(self.model, field) == value)
                    count_query = count_query.where(getattr(self.model, field) == value)

        # 计算总数
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 排序
        if order_by and hasattr(self.model, order_by):
            order_column = getattr(self.model, order_by)
            query = query.order_by(desc(order_column) if order_desc else asc(order_column))

        # 分页
        skip = (page - 1) * page_size
        query = query.offset(skip).limit(page_size)

        result = await db.execute(query)
        items = result.scalars().all()

        return items, total

    # ==================== 软删除操作 ====================

    async def delete(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        软删除记录（标记 is_deleted=True）

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交
        """
        obj = await self.get(db, id=id, include_deleted=False)
        if obj:
            obj.is_deleted = True
            obj.deleted_at = datetime.now(timezone.utc)
            db.add(obj)
            await db.flush()
            await db.refresh(obj)
            if commit:
                await db.commit()
        return obj

    async def delete_multi(
        self, db: AsyncSession, *, ids: List[int], commit: bool = True
    ) -> int:
        """
        批量软删除

        Args:
            db: 数据库会话
            ids: 记录 ID 列表
            commit: 是否自动提交
        """
        if not ids:
            return 0
        stmt = (
            sql_update(self.model)
            .where(self.model.id.in_(ids))
            .where(self.model.is_deleted == False)  # noqa: E712
            .values(is_deleted=True, deleted_at=datetime.now(timezone.utc))
        )
        result = await db.execute(stmt)
        await db.flush()
        if commit:
            await db.commit()
        return result.rowcount

    async def restore(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        恢复已删除的记录

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交
        """
        obj = await self.get(db, id=id, include_deleted=True)
        if obj and obj.is_deleted:
            obj.is_deleted = False
            obj.deleted_at = None
            db.add(obj)
            await db.flush()
            await db.refresh(obj)
            if commit:
                await db.commit()
        return obj

    async def restore_multi(
        self, db: AsyncSession, *, ids: List[int], commit: bool = True
    ) -> int:
        """
        批量恢复已删除的记录

        Args:
            db: 数据库会话
            ids: 记录 ID 列表
            commit: 是否自动提交
        """
        if not ids:
            return 0
        stmt = (
            sql_update(self.model)
            .where(self.model.id.in_(ids))
            .where(self.model.is_deleted == True)  # noqa: E712
            .values(is_deleted=False, deleted_at=None)
        )
        result = await db.execute(stmt)
        await db.flush()
        if commit:
            await db.commit()
        return result.rowcount

    # ==================== 物理删除（谨慎使用） ====================

    async def hard_delete(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        物理删除记录（不可恢复！谨慎使用）

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交
        """
        obj = await self.get(db, id=id, include_deleted=True)
        if obj:
            await db.delete(obj)
            await db.flush()
            if commit:
                await db.commit()
        return obj

    # ==================== 查询已删除记录 ====================

    async def get_deleted(
        self,
        db: AsyncSession,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> Sequence[ModelType]:
        """获取已删除的记录"""
        query = (
            select(self.model)
            .where(self.model.is_deleted == True)  # noqa: E712
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return result.scalars().all()

    async def count_deleted(self, db: AsyncSession) -> int:
        """统计已删除记录数"""
        query = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.is_deleted == True)  # noqa: E712
        )
        result = await db.execute(query)
        return result.scalar() or 0

    # ==================== Override 统计操作 ====================

    async def count(
        self,
        db: AsyncSession,
        *,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
    ) -> int:
        """统计记录数（默认排除已删除）"""
        query = select(func.count()).select_from(self.model)

        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712

        if filters:
            for field, value in filters.items():
                if hasattr(self.model, field) and value is not None:
                    query = query.where(getattr(self.model, field) == value)

        result = await db.execute(query)
        return result.scalar() or 0

    async def exists(
        self,
        db: AsyncSession,
        *,
        id: int,
        include_deleted: bool = False
    ) -> bool:
        """检查记录是否存在（默认排除已删除）"""
        query = (
            select(func.count())
            .select_from(self.model)
            .where(self.model.id == id)
        )
        if not include_deleted:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        result = await db.execute(query)
        return (result.scalar() or 0) > 0
