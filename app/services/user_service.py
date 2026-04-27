"""用户服务

演示 Service 层的使用方式，将业务逻辑从 API 层分离。

使用示例:
    from app.services.user_service import user_service

    # 在 API 端点中
    @router.post("/register")
    async def register(user_in: UserCreate, db: AsyncSession = Depends(get_async_db)):
        user = await user_service.register(db, user_in)
        return Response(data=user)
"""
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.base import BaseService, log_operation
from app.crud import user as user_crud
from app.models.user import User
from app.schemas.user import UserCreate
from app.core.exceptions import DuplicateError, NotFoundError, BadRequestError, AuthenticationError
from app.core.security import verify_password_async, get_password_hash_async
from app.core.logger import logger


class UserService(BaseService[User]):
    """
    用户服务

    封装用户相关的业务逻辑：
    - 用户注册
    - 用户认证
    - 密码重置
    - 用户状态管理
    """

    def __init__(self):
        super().__init__(crud=user_crud, cache_prefix="user")

    @log_operation("用户注册")
    async def register(
        self,
        db: AsyncSession,
        user_in: UserCreate,
    ) -> User:
        """
        用户注册

        Args:
            db: 数据库会话
            user_in: 注册信息

        Returns:
            创建的用户对象

        Raises:
            DuplicateError: 用户名或邮箱已存在
        """
        # 检查用户名是否已存在
        existing = await user_crud.get_by_username(db, username=user_in.username)
        if existing:
            raise DuplicateError("用户名已存在")

        # 检查邮箱是否已存在
        existing = await user_crud.get_by_email(db, email=user_in.email)
        if existing:
            raise DuplicateError("邮箱已注册")

        # 创建用户
        user = await user_crud.create(db, obj_in=user_in)

        logger.info("新用户注册成功: {} (ID: {})", user.username, user.id)
        return user

    async def authenticate(
        self,
        db: AsyncSession,
        username: str,
        password: str,
    ) -> Optional[User]:
        """
        用户认证

        Args:
            db: 数据库会话
            username: 用户名
            password: 密码

        Returns:
            认证成功返回用户对象，失败返回 None
        """
        # 查找用户
        user = await user_crud.get_by_username(db, username=username)
        if not user:
            return None

        # 验证密码
        if not await verify_password_async(password, user.hashed_password):
            return None

        # 检查用户状态
        if not user.is_active:
            return None

        return user

    @log_operation("修改密码")
    async def change_password(
        self,
        db: AsyncSession,
        user_id: int,
        old_password: str,
        new_password: str,
    ) -> bool:
        """
        修改密码

        Args:
            db: 数据库会话
            user_id: 用户 ID
            old_password: 旧密码
            new_password: 新密码

        Returns:
            是否成功

        Raises:
            NotFoundError: 用户不存在
            AuthenticationError: 旧密码错误
        """
        user = await user_crud.get(db, id=user_id)
        if not user:
            raise NotFoundError("用户不存在")

        # 验证旧密码
        if not await verify_password_async(old_password, user.hashed_password):
            raise AuthenticationError("原密码错误")

        # 更新密码
        hashed_password = await get_password_hash_async(new_password)
        await user_crud.update(db, db_obj=user, obj_in={"hashed_password": hashed_password})

        # 清除缓存（Redis + 进程内）
        await self.invalidate_cache(self._cache_key("id", user_id))
        from app.api.deps import invalidate_user_cache
        invalidate_user_cache(user_id)

        logger.info("用户 {} 修改密码成功", user.username)
        return True

    @log_operation("重置密码")
    async def reset_password(
        self,
        db: AsyncSession,
        user_id: int,
        new_password: str,
    ) -> bool:
        """
        重置密码（管理员操作）

        Args:
            db: 数据库会话
            user_id: 用户 ID
            new_password: 新密码

        Returns:
            是否成功
        """
        user = await user_crud.get(db, id=user_id)
        if not user:
            raise NotFoundError("用户不存在")

        hashed_password = await get_password_hash_async(new_password)
        await user_crud.update(db, db_obj=user, obj_in={"hashed_password": hashed_password})

        # 清除缓存（Redis + 进程内）
        await self.invalidate_cache(self._cache_key("id", user_id))
        from app.api.deps import invalidate_user_cache
        invalidate_user_cache(user_id)

        logger.info("管理员重置用户 {} 的密码", user.username)
        return True

    async def activate_user(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> User:
        """激活用户"""
        user = await user_crud.get(db, id=user_id)
        if not user:
            raise NotFoundError("用户不存在")

        user = await user_crud.update(db, db_obj=user, obj_in={"is_active": True})
        await self.invalidate_cache(self._cache_key("id", user_id))
        from app.api.deps import invalidate_user_cache
        invalidate_user_cache(user_id)

        return user

    async def deactivate_user(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> User:
        """禁用用户"""
        user = await user_crud.get(db, id=user_id)
        if not user:
            raise NotFoundError("用户不存在")

        if user.is_superuser:
            raise BadRequestError("不能禁用超级管理员")

        user = await user_crud.update(db, db_obj=user, obj_in={"is_active": False})
        await self.invalidate_cache(self._cache_key("id", user_id))
        from app.api.deps import invalidate_user_cache
        invalidate_user_cache(user_id)

        return user

    async def get_user_with_cache(
        self,
        db: AsyncSession,
        user_id: int,
        cache_ttl: int = 300,
    ) -> Optional[User]:
        """
        获取用户（带缓存）

        缓存策略：
        - 缓存中存储用户 ID（作为存在性标记）
        - 命中缓存后仍从 DB 获取完整 ORM 对象（保证数据一致性）
        - 缓存的价值在于避免不存在用户的重复查询（穿透防护）

        如需完全跳过 DB 查询，请使用 BaseService.get_by_id(use_cache=True)
        """
        cache_key = self._cache_key("id", user_id)

        # 尝试从缓存检查用户是否存在
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                if cached == "__NOT_FOUND__":
                    # 缓存了"不存在"标记，直接返回 None（防止缓存穿透）
                    return None
                logger.debug("缓存命中用户: {}", user_id)
                return await user_crud.get(db, id=user_id)

        # 从数据库获取
        user = await user_crud.get(db, id=user_id)

        # 存入缓存
        if self.cache:
            if user:
                await self.cache.set(cache_key, {"id": user.id, "username": user.username}, ttl=cache_ttl)
            else:
                # 缓存"不存在"标记，防止缓存穿透（短 TTL）
                await self.cache.set(cache_key, "__NOT_FOUND__", ttl=min(60, cache_ttl))

        return user

    async def search_users(
        self,
        db: AsyncSession,
        *,
        keyword: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[User], int]:
        """
        搜索用户

        Args:
            db: 数据库会话
            keyword: 搜索关键词（用户名/邮箱）
            is_active: 是否激活
            page: 页码
            page_size: 每页数量

        Returns:
            (用户列表, 总数)
        """
        from sqlalchemy import select, func, or_

        query = select(User)
        count_query = select(func.count()).select_from(User)

        # 关键词搜索
        if keyword:
            keyword = keyword.strip()
            filter_stmt = or_(
                User.username.ilike(f"%{keyword}%"),
                User.email.ilike(f"%{keyword}%"),
                User.full_name.ilike(f"%{keyword}%")
            )
            query = query.where(filter_stmt)
            count_query = count_query.where(filter_stmt)

        # 状态过滤
        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)

        # 总数
        total = await db.scalar(count_query) or 0

        # 分页
        skip = (page - 1) * page_size
        result = await db.execute(query.offset(skip).limit(page_size))
        users = result.scalars().all()

        return list(users), total


# 全局实例
user_service = UserService()
