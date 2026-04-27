"""用户 CRUD 操作 (异步)"""
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash_async


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    """用户 CRUD 操作"""

    async def get_by_username(self, db: AsyncSession, *, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, *, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, *, obj_in: UserCreate, commit: bool = True) -> User:
        """创建用户（密码哈希，异步执行避免阻塞事件循环）"""
        hashed_pw = await get_password_hash_async(obj_in.password)
        db_obj = User(
            username=obj_in.username,
            email=obj_in.email,
            hashed_password=hashed_pw,
            full_name=obj_in.full_name,
            avatar=obj_in.avatar,
        )
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        if commit:
            await db.commit()
        return db_obj

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: User,
        obj_in: UserUpdate | dict,
        commit: bool = True
    ) -> User:
        """更新用户"""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        # 如果更新密码，需要哈希
        if "password" in update_data:
            hashed_password = await get_password_hash_async(update_data["password"])
            del update_data["password"]
            update_data["hashed_password"] = hashed_password

        return await super().update(db, db_obj=db_obj, obj_in=update_data, commit=commit)

    async def authenticate(
        self,
        db: AsyncSession,
        *,
        username: str,
        password: str
    ) -> Optional[User]:
        """验证用户名和密码（异步版本，使用线程池执行 bcrypt）"""
        from app.core.security import verify_password_async

        user = await self.get_by_username(db, username=username)
        if not user:
            return None
        # 使用异步版本避免阻塞事件循环
        if not await verify_password_async(password, user.hashed_password):
            return None
        return user

    def is_active(self, user: User) -> bool:
        """检查用户是否激活"""
        return user.is_active

    def is_superuser(self, user: User) -> bool:
        """检查是否是超级用户"""
        return user.is_superuser


# 全局用户 CRUD 实例
user = CRUDUser(User)
