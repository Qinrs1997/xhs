"""公告 CRUD 操作 (异步) - 支持部门定向发送"""
from typing import Optional, List
from sqlalchemy import select, func, desc, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.base import CRUDBase
from app.models.announcement import Announcement, AnnouncementDepartment, TargetType
from app.schemas.announcement import AnnouncementCreate, AnnouncementUpdate
from app.core.timezone import now_local


class CRUDAnnouncement(CRUDBase[Announcement, AnnouncementCreate, AnnouncementUpdate]):
    """公告 CRUD 操作类"""

    async def get_list(
        self,
        db: AsyncSession,
        *,
        keyword: Optional[str] = None,
        published_only: bool = True,
        type: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
        is_superuser: bool = False,
        user_dept_ids: Optional[List[int]] = None
    ) -> tuple[List[Announcement], int]:
        """
        获取公告列表

        Args:
            db: 数据库会话
            keyword: 搜索关键词
            published_only: 是否只显示已发布
            type: 公告类型筛选
            skip: 跳过数量
            limit: 限制数量
            is_superuser: 是否超级管理员
            user_dept_ids: 用户所属部门ID列表（普通用户需要传入）

        Returns:
            (公告列表, 总数)
        """
        filters = []

        # 发布状态过滤
        if not is_superuser:
            filters.append(Announcement.is_published.is_(True))
        elif published_only:
            filters.append(Announcement.is_published.is_(True))

        if type:
            filters.append(Announcement.type == type)

        if keyword:
            keyword = keyword.strip()
            filters.append(or_(
                Announcement.title.ilike(f"%{keyword}%"),
                Announcement.content.ilike(f"%{keyword}%")
            ))

        # 🔑 关键：部门权限过滤（非管理员）
        if not is_superuser and user_dept_ids is not None:
            # 普通用户只能看到:
            # 1. target_type='all' 的公告
            # 2. target_type='dept' 且指定了用户所属部门的公告
            dept_filter = or_(
                Announcement.target_type == TargetType.ALL,
                and_(
                    Announcement.target_type == TargetType.DEPT,
                    Announcement.id.in_(
                        select(AnnouncementDepartment.announcement_id)
                        .where(AnnouncementDepartment.department_id.in_(user_dept_ids))
                    )
                )
            )
            filters.append(dept_filter)

        query = select(Announcement).options(selectinload(Announcement.target_departments))
        count_query = select(func.count()).select_from(Announcement)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)

        # 总数
        total = await db.scalar(count_query) or 0

        # 分页与排序
        query = query.order_by(
            desc(Announcement.is_published),
            desc(Announcement.published_at),
            desc(Announcement.created_at)
        ).offset(skip).limit(limit)

        result = await db.execute(query)
        items = list(result.scalars().all())

        return items, total

    async def create_announcement(
        self,
        db: AsyncSession,
        *,
        obj_in: AnnouncementCreate,
        author_id: int,
        author_name: str
    ) -> Announcement:
        """创建公告"""
        published_at = obj_in.published_at
        if obj_in.is_published and not published_at:
            published_at = now_local("Asia/Shanghai")

        announcement = Announcement(
            title=obj_in.title,
            content=obj_in.content,
            type=obj_in.type,
            is_published=obj_in.is_published,
            published_at=published_at,
            author_id=author_id,
            author_name=author_name,
            target_type=obj_in.target_type,
        )

        db.add(announcement)
        await db.flush()  # 获取 ID

        # 如果是部门定向，添加关联
        if obj_in.target_type == TargetType.DEPT and obj_in.dept_ids:
            await self._set_target_departments(db, announcement.id, obj_in.dept_ids)

        await db.commit()
        await db.refresh(announcement)

        return announcement

    async def update_announcement(
        self,
        db: AsyncSession,
        *,
        db_obj: Announcement,
        obj_in: AnnouncementUpdate,
        author_id: int,
        author_name: str
    ) -> Announcement:
        """更新公告"""
        update_data = obj_in.model_dump(exclude_unset=True)

        # 处理发布时间
        if update_data.get("is_published") is True and not db_obj.published_at and not update_data.get("published_at"):
            update_data["published_at"] = now_local("Asia/Shanghai")

        # 提取 dept_ids（不是模型字段）
        dept_ids = update_data.pop("dept_ids", None)

        # 更新基本字段
        for field, value in update_data.items():
            setattr(db_obj, field, value)

        db_obj.author_id = author_id
        db_obj.author_name = author_name

        db.add(db_obj)

        # 更新部门关联
        target_type = update_data.get("target_type", db_obj.target_type)
        if target_type == TargetType.DEPT and dept_ids is not None:
            await self._set_target_departments(db, db_obj.id, dept_ids)
        elif target_type == TargetType.ALL:
            # 如果改为全员，清除部门关联
            await self._clear_target_departments(db, db_obj.id)

        await db.commit()
        await db.refresh(db_obj)

        return db_obj

    async def _set_target_departments(
        self,
        db: AsyncSession,
        announcement_id: int,
        dept_ids: List[int]
    ) -> None:
        """设置目标部门（先清除再添加）"""
        # 清除旧关联
        await self._clear_target_departments(db, announcement_id)

        # 添加新关联
        for dept_id in dept_ids:
            link = AnnouncementDepartment(
                announcement_id=announcement_id,
                department_id=dept_id
            )
            db.add(link)

    async def _clear_target_departments(
        self,
        db: AsyncSession,
        announcement_id: int
    ) -> None:
        """清除目标部门关联"""
        result = await db.execute(
            select(AnnouncementDepartment).where(
                AnnouncementDepartment.announcement_id == announcement_id
            )
        )
        links = result.scalars().all()
        for link in links:
            await db.delete(link)

    async def can_view(
        self,
        db: AsyncSession,
        *,
        id: int,
        is_superuser: bool = False,
        user_dept_ids: Optional[List[int]] = None
    ) -> tuple[Optional[Announcement], bool]:
        """
        检查用户是否有权查看公告

        Args:
            db: 数据库会话
            id: 公告ID
            is_superuser: 是否超级管理员
            user_dept_ids: 用户所属部门ID列表

        Returns:
            (公告对象, 是否有权查看)
        """
        result = await db.execute(
            select(Announcement)
            .options(selectinload(Announcement.target_departments))
            .where(Announcement.id == id)
        )
        announcement = result.scalar_one_or_none()

        if not announcement:
            return None, False

        # 未发布的公告只有管理员能看
        if not announcement.is_published and not is_superuser:
            return announcement, False

        # 管理员可以看所有
        if is_superuser:
            return announcement, True

        # 全员公告所有人可见
        if announcement.target_type == TargetType.ALL:
            return announcement, True

        # 部门定向公告，检查用户是否在目标部门
        if user_dept_ids:
            target_ids = announcement.target_dept_ids
            if any(dept_id in target_ids for dept_id in user_dept_ids):
                return announcement, True

        return announcement, False

    async def get_with_departments(
        self,
        db: AsyncSession,
        *,
        id: int
    ) -> Optional[Announcement]:
        """获取公告详情（包含部门信息）"""
        result = await db.execute(
            select(Announcement)
            .options(
                selectinload(Announcement.target_departments)
                .selectinload(AnnouncementDepartment.department)
            )
            .where(Announcement.id == id)
        )
        return result.scalar_one_or_none()


# 全局公告 CRUD 实例
announcement = CRUDAnnouncement(Announcement)

