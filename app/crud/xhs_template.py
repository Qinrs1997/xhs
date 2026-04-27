"""小红书模板 CRUD"""
from typing import Optional, List, Sequence, Any
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.xhs_template import XHSTemplate


class CRUDXHSTemplate:
    """小红书模板 CRUD 操作"""

    async def get_active_list(
        self,
        db: AsyncSession,
        *,
        category: Optional[str] = None,
    ) -> Sequence[XHSTemplate]:
        """获取启用的模板列表"""
        stmt = select(XHSTemplate).where(XHSTemplate.is_active.is_(True))

        if category:
            stmt = stmt.where(XHSTemplate.category == category)

        stmt = stmt.order_by(XHSTemplate.sort_order.desc(), XHSTemplate.id.asc())
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_admin_list(
        self,
        db: AsyncSession,
        *,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_pro: Optional[bool] = None,
        author_id: Optional[int] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[XHSTemplate], int]:
        """管理端分页列表，含下架、支持多条件筛选。

        返回 (items, total)。
        """
        base = select(XHSTemplate)
        conds = []
        if category:
            conds.append(XHSTemplate.category == category)
        if is_active is not None:
            conds.append(XHSTemplate.is_active.is_(is_active))
        if is_pro is not None:
            conds.append(XHSTemplate.is_pro.is_(is_pro))
        if author_id is not None:
            conds.append(XHSTemplate.author_id == author_id)
        if keyword:
            kw = f"%{keyword}%"
            conds.append(XHSTemplate.name.ilike(kw))

        if conds:
            base = base.where(*conds)

        total_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(total_stmt)).scalar_one()

        stmt = base.order_by(
            XHSTemplate.sort_order.desc(), XHSTemplate.id.desc()
        ).limit(limit).offset(offset)
        rows = (await db.execute(stmt)).scalars().all()
        return rows, int(total)

    async def get_by_id(
        self,
        db: AsyncSession,
        *,
        template_id: int,
        include_inactive: bool = False,
    ) -> Optional[XHSTemplate]:
        """根据 ID 获取模板

        默认仅返回 `is_active=True` 的记录,避免已下架模板依然可通过深链命中。
        管理端如需查看所有记录可显式传 `include_inactive=True`。
        """
        stmt = select(XHSTemplate).where(XHSTemplate.id == template_id)
        if not include_inactive:
            stmt = stmt.where(XHSTemplate.is_active.is_(True))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_category_stats(
        self,
        db: AsyncSession,
    ) -> List[dict]:
        """获取分类统计"""
        stmt = (
            select(
                XHSTemplate.category,
                func.count(XHSTemplate.id).label("count")
            )
            .where(XHSTemplate.is_active.is_(True))
            .group_by(XHSTemplate.category)
            .order_by(func.count(XHSTemplate.id).desc())
        )
        result = await db.execute(stmt)
        return [{"key": row.category, "count": row.count} for row in result.all()]

    async def increment_use_count(
        self,
        db: AsyncSession,
        *,
        template_id: int,
    ) -> None:
        """模板使用次数 +1（原子操作）"""
        await db.execute(
            update(XHSTemplate)
            .where(XHSTemplate.id == template_id)
            .values(use_count=XHSTemplate.use_count + 1)
        )
        await db.flush()

    async def create(
        self,
        db: AsyncSession,
        *,
        data: dict[str, Any],
    ) -> XHSTemplate:
        """创建模板"""
        obj = XHSTemplate(**data)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        await db.commit()
        return obj

    async def update(
        self,
        db: AsyncSession,
        *,
        template_id: int,
        data: dict[str, Any],
    ) -> Optional[XHSTemplate]:
        """部分更新模板（只更新传入的字段）"""
        obj = await self.get_by_id(db, template_id=template_id, include_inactive=True)
        if not obj:
            return None
        for k, v in data.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        await db.commit()
        return obj

    async def delete(
        self,
        db: AsyncSession,
        *,
        template_id: int,
        hard: bool = False,
    ) -> bool:
        """删除模板。默认软删除（is_active=False），hard=True 时物理删除。"""
        if hard:
            res = await db.execute(
                delete(XHSTemplate).where(XHSTemplate.id == template_id)
            )
            await db.commit()
            return (res.rowcount or 0) > 0
        obj = await self.get_by_id(db, template_id=template_id, include_inactive=True)
        if not obj:
            return False
        obj.is_active = False
        db.add(obj)
        await db.commit()
        return True


# 分类标签映射
CATEGORY_LABELS = {
    "food": "🍽️ 美食",
    "fashion": "👗 穿搭",
    "travel": "✈️ 旅行",
    "home": "🏠 家居",
    "beauty": "💄 美妆",
    "fitness": "💪 健身",
    "study": "📚 学习",
    "pet": "🐾 宠物",
    "tech": "💻 科技",
    "medicine": "💊 药品",
    "life": "🌈 生活",
}


# 全局实例
xhs_template = CRUDXHSTemplate()
