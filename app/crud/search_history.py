"""搜索历史 CRUD

提供搜索历史的增删改查操作，所有查询按用户隔离。
"""
from typing import Optional, Sequence, Tuple, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.search_history import SearchHistory, SearchGeneratedTask
from app.schemas.search_history import SearchHistoryCreate, SearchHistoryUpdate
from app.core.logger import logger


class CRUDSearchHistory(CRUDBase[SearchHistory, SearchHistoryCreate, SearchHistoryUpdate]):
    """搜索历史 CRUD"""

    async def create_for_user(
        self,
        db: AsyncSession,
        *,
        obj_in: SearchHistoryCreate,
        user_id: int,
        commit: bool = True,
    ) -> SearchHistory:
        """为指定用户创建搜索历史记录"""
        obj_data = obj_in.model_dump(exclude_unset=True)
        obj_data["user_id"] = user_id
        db_obj = self.model(**obj_data)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        if commit:
            await db.commit()
        return db_obj

    async def get_list_by_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[Sequence[SearchHistory], int]:
        """分页获取用户搜索历史列表

        Args:
            user_id: 用户 ID
            page: 页码（从1开始）
            page_size: 每页数量
            keyword: 关键词模糊匹配 query 字段
            status: 状态过滤

        Returns:
            (记录列表, 总数)
        """
        # 构建 WHERE 条件
        conditions = [SearchHistory.user_id == user_id]
        if keyword:
            safe_kw = keyword.replace("%", r"\%").replace("_", r"\_")
            conditions.append(SearchHistory.query.ilike(f"%{safe_kw}%"))
        if status:
            conditions.append(SearchHistory.status == status)

        # 计数
        count_query = select(func.count()).select_from(SearchHistory).where(*conditions)
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # 分页查询（按创建时间倒序，eager load 关联任务避免 N+1）
        query = (
            select(SearchHistory)
            .options(selectinload(SearchHistory.generated_task_links))
            .where(*conditions)
            .order_by(SearchHistory.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = result.scalars().all()

        return items, total

    async def get_detail(
        self,
        db: AsyncSession,
        *,
        id: int,
        user_id: int,
    ) -> Optional[SearchHistory]:
        """获取搜索历史详情（含关联任务）

        校验用户归属权。
        """
        query = (
            select(SearchHistory)
            .options(selectinload(SearchHistory.generated_task_links))
            .where(SearchHistory.id == id, SearchHistory.user_id == user_id)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def delete_by_user(
        self,
        db: AsyncSession,
        *,
        id: int,
        user_id: int,
        commit: bool = True,
    ) -> bool:
        """删除搜索历史（校验用户归属权）

        Returns:
            True 删除成功, False 记录不存在或不属于该用户
        """
        query = select(SearchHistory).where(
            SearchHistory.id == id,
            SearchHistory.user_id == user_id,
        )
        result = await db.execute(query)
        obj = result.scalar_one_or_none()

        if not obj:
            return False

        await db.delete(obj)
        await db.flush()
        if commit:
            await db.commit()
        return True

    async def link_task_if_not_exists(
        self,
        db: AsyncSession,
        *,
        search_history_id: int,
        task_id: int,
        user_id: int | None = None,
        commit: bool = True,
    ) -> Optional[SearchGeneratedTask]:
        """关联搜索记录与任务（去重：已存在则跳过）

        Args:
            user_id: 可选，传入时校验搜索记录归属，防止 IDOR

        Returns:
            新建的关联对象，若已存在则返回 None
        """
        if user_id is not None:
            from app.models.search_history import SearchHistory
            sh = await db.execute(
                select(SearchHistory.user_id).where(SearchHistory.id == search_history_id)
            )
            owner = sh.scalar_one_or_none()
            if owner is None or owner != user_id:
                logger.warning("搜索关联归属校验失败: search_id={}, user_id={}", search_history_id, user_id)
                return None

        existing = await db.execute(
            select(SearchGeneratedTask).where(
                SearchGeneratedTask.search_history_id == search_history_id,
                SearchGeneratedTask.task_id == task_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug("搜索关联已存在，跳过: search_id={}, task_id={}", search_history_id, task_id)
            return None

        link = SearchGeneratedTask(
            search_history_id=search_history_id,
            task_id=task_id,
        )
        db.add(link)
        await db.flush()
        if commit:
            await db.commit()
        return link

    async def add_generated_task(
        self,
        db: AsyncSession,
        *,
        search_history_id: int,
        task_id: int,
        commit: bool = True,
    ) -> SearchGeneratedTask:
        """添加搜索记录与任务的关联"""
        link = SearchGeneratedTask(
            search_history_id=search_history_id,
            task_id=task_id,
        )
        db.add(link)
        await db.flush()
        if commit:
            await db.commit()
        return link

    async def add_generated_tasks_batch(
        self,
        db: AsyncSession,
        *,
        search_history_id: int,
        task_ids: List[int],
        commit: bool = True,
    ) -> List[SearchGeneratedTask]:
        """批量添加搜索记录与任务的关联"""
        if not task_ids:
            return []

        links = []
        for task_id in task_ids:
            link = SearchGeneratedTask(
                search_history_id=search_history_id,
                task_id=task_id,
            )
            db.add(link)
            links.append(link)

        await db.flush()
        if commit:
            await db.commit()
        return links

    async def update_status(
        self,
        db: AsyncSession,
        *,
        id: int,
        status: str,
        commit: bool = True,
    ) -> Optional[SearchHistory]:
        """更新搜索记录状态"""
        obj = await self.get(db, id=id)
        if not obj:
            return None
        obj.status = status
        await db.flush()
        if commit:
            await db.commit()
        return obj

    async def get_generated_task_ids(
        self,
        db: AsyncSession,
        *,
        search_history_id: int,
    ) -> List[int]:
        """获取搜索记录关联的所有任务 ID"""
        query = (
            select(SearchGeneratedTask.task_id)
            .where(SearchGeneratedTask.search_history_id == search_history_id)
        )
        result = await db.execute(query)
        return [row[0] for row in result.all()]


# 模块级单例
search_history_crud = CRUDSearchHistory(SearchHistory)
