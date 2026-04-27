"""异步 CRUD 操作基类

提供通用的异步 CRUD 操作，继承此类可快速实现数据访问层。

⚠️ 重要说明：
- 写操作（create/update/delete）默认会自动 commit
- 如需在一个事务中执行多个操作，请设置 commit=False，最后手动调用 await db.commit()

使用示例：
    from app.crud.base import CRUDBase

    class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
        async def get_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
            result = await db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()

    user_crud = CRUDUser(User)
"""
from typing import Generic, TypeVar, Type, Optional, Any, Dict, Tuple, List, Sequence
from pydantic import BaseModel
from sqlalchemy import select, func, asc, desc, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base, SoftDeleteModel
from app.core import context

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    异步通用 CRUD 基类

    提供基本的异步 CRUD 操作，可被具体模型的 CRUD 类继承和扩展。

    Args:
        model: SQLAlchemy 模型类
    """

    _OP_MAP = {
        "gt": lambda col, val: col > val,
        "gte": lambda col, val: col >= val,
        "lt": lambda col, val: col < val,
        "lte": lambda col, val: col <= val,
        "ne": lambda col, val: col != val,
        "like": lambda col, val: col.like(val),
        "ilike": lambda col, val: col.ilike(val),
        "in": lambda col, val: col.in_(val),
        "is_null": lambda col, val: col.is_(None) if val else col.isnot(None),
    }

    def __init__(self, model: Type[ModelType]):
        self.model = model
        self._has_soft_delete = issubclass(model, SoftDeleteModel)

    def _apply_soft_delete_filter(self, query):
        """自动为软删除模型追加 is_deleted=False 过滤"""
        if self._has_soft_delete:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        return query

    def _apply_filters(self, query, filters: Optional[Dict[str, Any]]):
        """
        应用 Django-style 过滤条件到查询

        支持的操作符后缀：
        - 无后缀: 精确等值匹配 (==)
        - __gt: 大于 (>)
        - __gte: 大于等于 (>=)
        - __lt: 小于 (<)
        - __lte: 小于等于 (<=)
        - __ne: 不等于 (!=)
        - __like: LIKE 匹配（需自带 % 通配符）
        - __ilike: 不区分大小写 LIKE
        - __in: IN 查询（值须为 list/tuple）
        - __is_null: IS NULL / IS NOT NULL（值为 True/False）

        使用示例:
            filters = {
                "status": 1,              # status == 1
                "age__gte": 18,           # age >= 18
                "name__like": "%test%",   # name LIKE '%test%'
                "role__in": [1, 2, 3],    # role IN (1, 2, 3)
                "deleted_at__is_null": True,  # deleted_at IS NULL
            }
        """
        if not filters:
            return query

        for key, value in filters.items():
            if value is None:
                continue

            parts = key.rsplit("__", 1)
            if len(parts) == 2 and parts[1] in self._OP_MAP:
                field_name, op = parts
            else:
                field_name, op = key, None

            if not hasattr(self.model, field_name):
                continue

            column = getattr(self.model, field_name)
            if op:
                query = query.where(self._OP_MAP[op](column, value))
            else:
                query = query.where(column == value)

        return query

    # ==================== 查询操作 ====================

    async def get(self, db: AsyncSession, id: int) -> Optional[ModelType]:
        """根据 ID 获取单条记录（自动过滤软删除）"""
        query = select(self.model).where(self.model.id == id)
        query = self._apply_soft_delete_filter(query)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_ids(self, db: AsyncSession, ids: List[int]) -> Sequence[ModelType]:
        """根据 ID 列表批量获取记录（自动过滤软删除）"""
        if not ids:
            return []
        query = select(self.model).where(self.model.id.in_(ids))
        query = self._apply_soft_delete_filter(query)
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
        filters: Optional[Dict[str, Any]] = None,
    ) -> Sequence[ModelType]:
        """
        获取多条记录

        Args:
            db: 异步数据库会话
            skip: 跳过记录数
            limit: 返回记录数
            order_by: 排序字段名
            order_desc: 是否降序（默认升序）
            filters: 过滤条件（支持 Django-style 操作符，与 get_multi_paginated 一致）
        """
        query = select(self.model)
        query = self._apply_soft_delete_filter(query)
        query = self._apply_filters(query, filters)

        # 排序（无指定时默认按 id 降序，避免 MySQL 分页结果不稳定）
        if order_by and hasattr(self.model, order_by):
            order_column = getattr(self.model, order_by)
            query = query.order_by(desc(order_column) if order_desc else asc(order_column))
        else:
            query = query.order_by(desc(self.model.id))

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
    ) -> Tuple[Sequence[ModelType], int]:
        """
        分页获取记录

        Args:
            db: 异步数据库会话
            page: 页码（从1开始）
            page_size: 每页记录数
            order_by: 排序字段名
            order_desc: 是否降序
            filters: 过滤条件（字段名: 值）

        Returns:
            (记录列表, 总数)
        """
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)

        # 软删除过滤
        query = self._apply_soft_delete_filter(query)
        if self._has_soft_delete:
            count_query = count_query.where(self.model.is_deleted == False)  # noqa: E712

        # 应用过滤条件（支持操作符）
        query = self._apply_filters(query, filters)
        count_query = self._apply_filters(count_query, filters)

        # 计算总数
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 排序（无指定时默认按 id 降序）
        if order_by and hasattr(self.model, order_by):
            order_column = getattr(self.model, order_by)
            query = query.order_by(desc(order_column) if order_desc else asc(order_column))
        else:
            query = query.order_by(desc(self.model.id))

        # 分页
        skip = (page - 1) * page_size
        query = query.offset(skip).limit(page_size)

        result = await db.execute(query)
        items = result.scalars().all()

        return items, total

    # ==================== 写操作 ====================

    async def create(
        self, db: AsyncSession, *, obj_in: CreateSchemaType, commit: bool = True
    ) -> ModelType:
        """
        创建记录

        Args:
            db: 数据库会话
            obj_in: 创建数据
            commit: 是否自动提交（默认 True）
        """
        # 优先使用 Pydantic v2 的 model_dump（保留原始类型，性能更好）
        if isinstance(obj_in, BaseModel):
            obj_in_data = obj_in.model_dump(exclude_unset=True)
        else:
            obj_in_data = dict(obj_in) if hasattr(obj_in, '__iter__') else {}
        db_obj = self.model(**obj_in_data)

        # 自动审计字段
        user_id = context.get_current_user_id()
        if user_id:
            if hasattr(db_obj, "creator_id"):
                db_obj.creator_id = user_id
            if hasattr(db_obj, "updater_id"):
                db_obj.updater_id = user_id

        db.add(db_obj)
        await db.flush()  # 获取自增 ID
        await db.refresh(db_obj)
        if commit:
            await db.commit()
        return db_obj

    async def create_multi(
        self, db: AsyncSession, *, objs_in: List[CreateSchemaType], commit: bool = True
    ) -> List[ModelType]:
        """
        批量创建记录

        Args:
            db: 数据库会话
            objs_in: 创建数据列表
            commit: 是否自动提交（默认 True）
        """
        db_objs = []
        user_id = context.get_current_user_id()
        for obj_in in objs_in:
            if isinstance(obj_in, BaseModel):
                obj_in_data = obj_in.model_dump(exclude_unset=True)
            else:
                obj_in_data = dict(obj_in) if hasattr(obj_in, '__iter__') else {}
            db_obj = self.model(**obj_in_data)
            # 自动审计字段
            if user_id:
                if hasattr(db_obj, "creator_id"):
                    db_obj.creator_id = user_id
                if hasattr(db_obj, "updater_id"):
                    db_obj.updater_id = user_id
            db.add(db_obj)
            db_objs.append(db_obj)
        await db.flush()
        for db_obj in db_objs:
            await db.refresh(db_obj)
        if commit:
            await db.commit()
        return db_objs

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | Dict[str, Any],
        commit: bool = True
    ) -> ModelType:
        """
        更新记录

        Args:
            db: 数据库会话
            db_obj: 要更新的数据库对象
            obj_in: 更新数据
            commit: 是否自动提交（默认 True）
        """
        # 获取当前 ORM 对象的所有列名（仅用于字段过滤，无需取值）
        valid_fields = set(db_obj.__table__.columns.keys())

        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field in update_data:
            if field in valid_fields:
                setattr(db_obj, field, update_data[field])

        # 自动审计字段
        user_id = context.get_current_user_id()
        if user_id and hasattr(db_obj, "updater_id"):
            db_obj.updater_id = user_id

        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        if commit:
            await db.commit()
        return db_obj

    async def delete(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        删除记录

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交（默认 True）
        """
        obj = await self.get(db, id=id)
        if obj:
            await db.delete(obj)
            await db.flush()
            if commit:
                await db.commit()
        return obj

    async def delete_multi(
        self, db: AsyncSession, *, ids: List[int], commit: bool = True
    ) -> int:
        """
        批量删除记录，返回删除数量

        Args:
            db: 数据库会话
            ids: 记录 ID 列表
            commit: 是否自动提交（默认 True）
        """
        if not ids:
            return 0
        stmt = sql_delete(self.model).where(self.model.id.in_(ids))
        result = await db.execute(stmt)
        await db.flush()
        if commit:
            await db.commit()
        return result.rowcount

    # ==================== 统计操作 ====================

    async def count(
        self, db: AsyncSession, *, filters: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        统计记录数（自动过滤软删除）

        Args:
            db: 异步数据库会话
            filters: 过滤条件（字段名: 值）
        """
        query = select(func.count()).select_from(self.model)
        if self._has_soft_delete:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        query = self._apply_filters(query, filters)
        result = await db.execute(query)
        return result.scalar() or 0

    async def exists(self, db: AsyncSession, *, id: int) -> bool:
        """检查记录是否存在（自动过滤软删除）"""
        query = select(func.count()).select_from(self.model).where(self.model.id == id)
        if self._has_soft_delete:
            query = query.where(self.model.is_deleted == False)  # noqa: E712
        result = await db.execute(query)
        return (result.scalar() or 0) > 0

    async def get_multi_cursor(
        self,
        db: AsyncSession,
        *,
        cursor: Optional[int] = None,
        page_size: int = 20,
        order_desc: bool = False,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Sequence[ModelType], Optional[int]]:
        """
        基于游标的分页查询（大表深翻页性能 O(1)）

        使用 WHERE id > cursor ORDER BY id LIMIT page_size 代替 OFFSET。

        Args:
            db: 异步数据库会话
            cursor: 上一页最后一条记录的 ID（首页传 None）
            page_size: 每页记录数
            order_desc: 是否降序（降序时使用 id < cursor）
            filters: 过滤条件（支持操作符，同 get_multi_paginated）

        Returns:
            (记录列表, 下一页游标)
            游标为 None 表示没有更多数据

        使用示例:
            # 首页
            items, next_cursor = await crud.get_multi_cursor(
                db, page_size=20
            )
            # 下一页
            items, next_cursor = await crud.get_multi_cursor(
                db, cursor=next_cursor, page_size=20
            )
        """
        query = select(self.model)
        query = self._apply_soft_delete_filter(query)
        query = self._apply_filters(query, filters)

        if cursor is not None:
            if order_desc:
                query = query.where(self.model.id < cursor)
            else:
                query = query.where(self.model.id > cursor)

        if order_desc:
            query = query.order_by(desc(self.model.id))
        else:
            query = query.order_by(asc(self.model.id))

        # 多取 1 条，用来判断是否还有下一页
        query = query.limit(page_size + 1)

        result = await db.execute(query)
        rows = list(result.scalars().all())

        if len(rows) > page_size:
            # 还有下一页
            items = rows[:page_size]
            next_cursor = items[-1].id
        else:
            items = rows
            next_cursor = None

        return items, next_cursor

    # ==================== 软删除操作 ====================

    async def soft_delete(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        软删除记录（仅对 SoftDeleteModel 子类有效）

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交
        """
        if not self._has_soft_delete:
            raise NotImplementedError(
                f"{self.model.__name__} 不支持软删除，请使用 delete() 方法"
            )

        obj = await self.get(db, id=id)
        if obj:
            obj.soft_delete()
            await db.flush()
            if commit:
                await db.commit()
        return obj

    async def restore(
        self, db: AsyncSession, *, id: int, commit: bool = True
    ) -> Optional[ModelType]:
        """
        恢复软删除的记录

        Args:
            db: 数据库会话
            id: 记录 ID
            commit: 是否自动提交
        """
        if not self._has_soft_delete:
            raise NotImplementedError(
                f"{self.model.__name__} 不支持软删除恢复"
            )

        # 查询时不过滤软删除 — 直接用 get_include_deleted
        result = await db.execute(
            select(self.model).where(self.model.id == id)
        )
        obj = result.scalar_one_or_none()
        if obj:
            obj.restore()
            await db.flush()
            if commit:
                await db.commit()
        return obj
