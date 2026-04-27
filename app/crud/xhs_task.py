"""XHS 任务 CRUD 操作

提供 XHS 任务的数据库增删改查操作。
"""
import copy
from datetime import datetime
from typing import Optional, Sequence
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.xhs.utils import get_page_num, normalize_page_order
from app.crud.base import CRUDBase
from app.models.xhs_task import XHSTask, TaskStatus
from app.schemas.xhs_task import XHSTaskCreate, XHSTaskUpdate
from app.core.timezone import now_utc


class CRUDXHSTask(CRUDBase[XHSTask, XHSTaskCreate, XHSTaskUpdate]):
    """XHS 任务 CRUD 操作"""

    async def create_for_user(
        self,
        db: AsyncSession,
        *,
        obj_in: XHSTaskCreate,
        user_id: int
    ) -> XHSTask:
        """
        为指定用户创建任务

        Args:
            db: 数据库会话
            obj_in: 创建数据
            user_id: 用户 ID

        Returns:
            创建的任务对象
        """
        # 计算页面数量
        page_count = len(obj_in.pages) if obj_in.pages else 0

        # 将 pages 转换为可序列化的字典列表
        pages_data = None
        if obj_in.pages:
            pages_data = normalize_page_order(
                [page.model_dump() for page in obj_in.pages]
            )

        task = XHSTask(
            user_id=user_id,
            title=obj_in.title,
            topic=obj_in.topic,
            status=obj_in.status,
            pages=pages_data,
            style=obj_in.style,
            model=obj_in.model,
            template_id=getattr(obj_in, "template_id", None),
            page_count=page_count,
            creator_id=user_id,
        )

        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    async def update_task(
        self,
        db: AsyncSession,
        *,
        task: XHSTask,
        obj_in: XHSTaskUpdate,
        user_id: int
    ) -> XHSTask:
        """
        更新任务

        Args:
            db: 数据库会话
            task: 任务对象
            obj_in: 更新数据
            user_id: 操作用户 ID

        Returns:
            更新后的任务对象
        """
        update_data = obj_in.model_dump(exclude_unset=True)

        # 处理 pages 字段
        if "pages" in update_data and update_data["pages"] is not None:
            pages = update_data["pages"]
            update_data["pages"] = normalize_page_order(
                [
                    page.model_dump() if hasattr(page, "model_dump") else page
                    for page in pages
                ]
            )
            update_data["page_count"] = len(pages)

        # 如果状态变为完成，记录完成时间
        if update_data.get("status") == TaskStatus.COMPLETED:
            update_data["completed_at"] = now_utc()

        # 更新字段
        for field, value in update_data.items():
            setattr(task, field, value)

        task.updater_id = user_id

        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    async def get_by_user(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        status: Optional[TaskStatus] = None,
        keyword: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 20
    ) -> tuple[Sequence[XHSTask], int]:
        """
        获取用户的任务列表（带分页和筛选）

        Args:
            db: 数据库会话
            user_id: 用户 ID
            status: 状态筛选
            keyword: 关键词搜索
            start_date: 开始日期
            end_date: 结束日期
            skip: 跳过数量
            limit: 限制数量

        Returns:
            (任务列表, 总数)
        """
        limit = min(limit, 100)

        conditions = [XHSTask.user_id == user_id]

        if status:
            conditions.append(XHSTask.status == status)

        if keyword:
            safe_kw = keyword.replace("%", r"\%").replace("_", r"\_")
            conditions.append(
                or_(
                    XHSTask.title.contains(safe_kw),
                    XHSTask.topic.contains(safe_kw)
                )
            )

        if start_date:
            conditions.append(XHSTask.created_at >= start_date)

        if end_date:
            conditions.append(XHSTask.created_at <= end_date)

        # 查询总数
        count_stmt = select(func.count(XHSTask.id)).where(and_(*conditions))
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        # 查询列表（selectinload 批量加载搜索关联，避免 N+1）
        from sqlalchemy.orm import selectinload
        query_stmt = (
            select(XHSTask)
            .options(selectinload(XHSTask.search_task_links))
            .where(and_(*conditions))
            .order_by(XHSTask.updated_at.desc(), XHSTask.id.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query_stmt)
        items = result.scalars().all()

        return items, total

    async def get_user_task(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        user_id: int
    ) -> Optional[XHSTask]:
        """
        获取用户的指定任务

        Args:
            db: 数据库会话
            task_id: 任务 ID
            user_id: 用户 ID

        Returns:
            任务对象或 None
        """
        result = await db.execute(
            select(XHSTask).where(
                XHSTask.id == task_id,
                XHSTask.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def update_page_field(
        self,
        db: AsyncSession,
        *,
        task: XHSTask,
        page_index: int,
        updates: dict,
    ) -> XHSTask:
        """更新任务中某一页的指定字段（如 image_prompt, image_url）

        Args:
            task: 任务对象
            page_index: 页面索引（0-based）
            updates: 要更新的字段字典，如 {"image_prompt": "xxx"}
        """
        pages = copy.deepcopy(task.pages or [])
        target_idx = next(
            (
                i
                for i, page in enumerate(pages)
                if get_page_num(page, i + 1) == page_index + 1
            ),
            page_index,
        )
        if 0 <= target_idx < len(pages):
            pages[target_idx].update(updates)
            task.pages = normalize_page_order(pages)
            task.updated_at = now_utc()
            # JSON 字段必须 flag_modified，否则 SQLAlchemy 不检测内部突变
            flag_modified(task, "pages")
            await db.flush()
        return task

    async def update_pages_batch(
        self,
        db: AsyncSession,
        *,
        task: XHSTask,
        field_name: str,
        values: list,
    ) -> XHSTask:
        """批量更新所有页面的某个字段

        Args:
            task: 任务对象
            field_name: 字段名，如 "image_prompt"
            values: 值列表，长度应与 pages 一致
        """
        pages = copy.deepcopy(task.pages or [])
        for i, val in enumerate(values):
            if val is None:
                continue
            target_idx = next(
                (
                    page_idx
                    for page_idx, page in enumerate(pages)
                    if get_page_num(page, page_idx + 1) == i + 1
                ),
                i,
            )
            if target_idx < len(pages):
                pages[target_idx][field_name] = val
        task.pages = normalize_page_order(pages)
        task.updated_at = now_utc()
        flag_modified(task, "pages")
        await db.flush()
        return task

    async def update_copywriting(
        self,
        db: AsyncSession,
        *,
        task: XHSTask,
        copywriting: dict,
    ) -> XHSTask:
        """更新任务的文案数据"""
        task.copywriting = copywriting
        task.updated_at = now_utc()
        await db.flush()
        return task

    async def add_tokens(
        self,
        db: AsyncSession,
        *,
        task: XHSTask,
        tokens: int,
    ) -> None:
        """累加任务消耗的 token 数"""
        task.total_tokens = (task.total_tokens or 0) + tokens
        await db.flush()


    async def delete_user_task(
        self,
        db: AsyncSession,
        *,
        task_id: int,
        user_id: int
    ) -> Optional[XHSTask]:
        """
        删除用户的指定任务

        Args:
            db: 数据库会话
            task_id: 任务 ID
            user_id: 用户 ID

        Returns:
            被删除的任务对象，不存在则返回 None
        """
        task = await self.get_user_task(db, task_id=task_id, user_id=user_id)
        if not task:
            return None

        # 先保留 pages 数据用于后续文件清理
        deleted_task = task
        await db.delete(task)
        await db.commit()
        return deleted_task

    async def get_user_task_stats(
        self,
        db: AsyncSession,
        *,
        user_id: int
    ) -> dict:
        """
        获取用户任务统计（优化版：1 次 SQL 搞定）

        Returns:
            统计数据字典
        """
        # 一次查询搞定所有状态计数 + 总页数 + 总 token
        stmt = (
            select(
                XHSTask.status,
                func.count(XHSTask.id).label("count"),
                func.coalesce(func.sum(XHSTask.page_count), 0).label("pages"),
                func.coalesce(func.sum(XHSTask.total_tokens), 0).label("tokens"),
            )
            .where(XHSTask.user_id == user_id)
            .group_by(XHSTask.status)
        )
        result = await db.execute(stmt)
        rows = result.all()

        # 初始化所有状态为 0
        stats = {s.value: 0 for s in TaskStatus}
        total = 0
        total_pages = 0
        total_tokens = 0

        for row in rows:
            stats[row.status.value] = row.count
            total += row.count
            total_pages += row.pages
            total_tokens += row.tokens

        stats["total"] = total
        stats["total_pages"] = total_pages
        stats["total_tokens"] = total_tokens

        return stats


# 全局 CRUD 实例
xhs_task = CRUDXHSTask(XHSTask)

