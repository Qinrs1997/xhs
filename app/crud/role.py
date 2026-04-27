"""角色与用户角色 CRUD (异步)"""
from typing import Optional, Iterable, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.role import Role, UserRole
from app.schemas.role import RoleCreate, RoleUpdate


class CRUDRole(CRUDBase[Role, RoleCreate, RoleUpdate]):
    """角色 CRUD 操作"""

    async def get_by_name(self, db: AsyncSession, *, name: str) -> Optional[Role]:
        """根据名称获取角色"""
        result = await db.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def assign_to_user(
        self, db: AsyncSession, *, user_id: int, role_id: int
    ) -> None:
        """为用户分配角色"""
        result = await db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id
            )
        )
        exists = result.scalar_one_or_none()
        if exists:
            return
        db.add(UserRole(user_id=user_id, role_id=role_id))
        await db.flush()

    async def remove_from_user(
        self, db: AsyncSession, *, user_id: int, role_id: int
    ) -> None:
        """移除用户角色"""
        result = await db.execute(
            select(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id
            )
        )
        link = result.scalar_one_or_none()
        if link:
            await db.delete(link)
            await db.flush()

    async def get_user_roles(
        self, db: AsyncSession, *, user_id: int
    ) -> Sequence[Role]:
        """获取用户的所有角色"""
        result = await db.execute(
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        return result.scalars().all()

    async def user_has_any_role(
        self, db: AsyncSession, *, user_id: int, role_names: Iterable[str]
    ) -> bool:
        """检查用户是否拥有指定角色之一"""
        role_names_list = list(role_names)
        if not role_names_list:
            return False
        result = await db.execute(
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user_id,
                Role.name.in_(role_names_list),
                Role.is_active == True  # noqa: E712
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


# 全局角色 CRUD 实例
role = CRUDRole(Role)
