"""Service 层基类

提供业务逻辑层的通用能力：
- 事务管理
- 缓存集成
- 日志记录
- 错误处理

使用示例:
    from app.services.base import BaseService
    from app.crud import user as user_crud
    from app.models.user import User

    class UserService(BaseService[User]):
        def __init__(self):
            super().__init__(crud=user_crud)

        async def register_user(self, db: AsyncSession, user_in: UserCreate) -> User:
            # 检查用户是否存在
            existing = await self.crud.get_by_email(db, email=user_in.email)
            if existing:
                raise DuplicateError("邮箱已注册")

            # 创建用户（使用事务装饰器自动管理）
            return await self.crud.create(db, obj_in=user_in)

    # 全局实例
    user_service = UserService()
"""
from typing import TypeVar, Generic, Optional, Any, Callable
from functools import wraps
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.core.context import get_request_id, get_current_user_id
# 统一使用 core/transaction.py 中的事务管理工具

ModelType = TypeVar("ModelType")


def log_operation(operation_name: str | None = None):
    """
    操作日志装饰器

    记录方法执行的开始、结束和耗时

    使用示例:
        @log_operation("用户注册")
        async def register(self, db, user_in):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import time

            name = operation_name or func.__name__
            request_id = get_request_id() or "no-req"
            user_id = get_current_user_id() or "anonymous"

            start = time.time()
            logger.info("[{}] [user:{}] 开始执行: {}", request_id[:8], user_id, name)

            try:
                result = await func(*args, **kwargs)
                elapsed = (time.time() - start) * 1000
                logger.info("[{}] [user:{}] 执行完成: {} | 耗时: {:.1f}ms", request_id[:8], user_id, name, elapsed)
                return result
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                logger.error("[{}] [user:{}] 执行失败: {} | 耗时: {:.1f}ms | 错误: {}", request_id[:8], user_id, name, elapsed, e)
                raise

        return wrapper
    return decorator


class BaseService(Generic[ModelType]):
    """
    Service 层基类

    提供：
    - CRUD 操作封装
    - 缓存集成
    - 日志记录
    - 事务管理辅助

    子类应该：
    1. 继承此类并指定模型类型
    2. 在 __init__ 中传入对应的 CRUD 实例
    3. 实现具体的业务方法

    示例:
        class UserService(BaseService[User]):
            def __init__(self):
                super().__init__(crud=user_crud)

            async def get_active_users(self, db: AsyncSession) -> list[User]:
                return await self.crud.get_multi(db, filters={"is_active": True})
    """

    def __init__(self, crud=None, cache_prefix: str | None = None):
        """
        初始化 Service

        Args:
            crud: CRUD 实例（可选，某些 Service 可能不需要）
            cache_prefix: 缓存 key 前缀（用于缓存集成）
        """
        self.crud = crud
        self.cache_prefix = cache_prefix or self.__class__.__name__.lower()
        self._cache = None  # 延迟加载

    @property
    def cache(self):
        """获取缓存实例（延迟加载）"""
        if self._cache is None:
            try:
                from app.core.cache import cache
                self._cache = cache
            except ImportError:
                self._cache = None
        return self._cache

    # ==================== 缓存辅助方法 ====================

    def _cache_key(self, *parts) -> str:
        """生成缓存 key"""
        return f"{self.cache_prefix}:" + ":".join(str(p) for p in parts)

    async def get_cached(
        self,
        key: str,
        fetch_func: Callable,
        ttl: int = 300,
        **fetch_kwargs
    ) -> Any:
        """
        获取缓存数据，不存在则调用 fetch_func 获取并缓存

        Args:
            key: 缓存 key
            fetch_func: 获取数据的函数
            ttl: 缓存时间（秒）
            **fetch_kwargs: 传给 fetch_func 的参数

        Returns:
            缓存或新获取的数据
        """
        if self.cache:
            cached = await self.cache.get(key)
            if cached is not None:
                return cached

        # 获取数据
        data = await fetch_func(**fetch_kwargs)

        # 缓存
        if self.cache and data is not None:
            await self.cache.set(key, data, ttl=ttl)

        return data

    async def invalidate_cache(self, *keys: str) -> None:
        """清除指定缓存"""
        if self.cache:
            for key in keys:
                await self.cache.delete(key)

    # ==================== 通用 CRUD 封装 ====================

    async def get_by_id(
        self,
        db: AsyncSession,
        id: int,
        use_cache: bool = False,
        cache_ttl: int = 300
    ) -> Optional[ModelType]:
        """
        根据 ID 获取记录

        Args:
            db: 数据库会话
            id: 记录 ID
            use_cache: 是否使用缓存
            cache_ttl: 缓存时间
        """
        if not self.crud:
            raise NotImplementedError("Service 未配置 CRUD")

        if use_cache:
            cache_key = self._cache_key("id", id)
            return await self.get_cached(
                cache_key,
                self.crud.get,
                ttl=cache_ttl,
                db=db,
                id=id
            )

        return await self.crud.get(db, id=id)

    async def get_list(
        self,
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: dict | None = None,
        order_by: str | None = None,
        order_desc: bool = False
    ) -> tuple[list[ModelType], int]:
        """
        获取分页列表

        Returns:
            (items, total)
        """
        if not self.crud:
            raise NotImplementedError("Service 未配置 CRUD")

        return await self.crud.get_multi_paginated(
            db,
            page=page,
            page_size=page_size,
            filters=filters,
            order_by=order_by,
            order_desc=order_desc
        )

    async def create(
        self,
        db: AsyncSession,
        *,
        obj_in,
        commit: bool = True
    ) -> ModelType:
        """创建记录"""
        if not self.crud:
            raise NotImplementedError("Service 未配置 CRUD")
        return await self.crud.create(db, obj_in=obj_in, commit=commit)

    async def update(
        self,
        db: AsyncSession,
        *,
        id: int,
        obj_in,
        commit: bool = True
    ) -> Optional[ModelType]:
        """更新记录"""
        if not self.crud:
            raise NotImplementedError("Service 未配置 CRUD")

        db_obj = await self.crud.get(db, id=id)
        if not db_obj:
            return None

        result = await self.crud.update(db, db_obj=db_obj, obj_in=obj_in, commit=commit)

        # 清除缓存
        await self.invalidate_cache(self._cache_key("id", id))

        return result

    async def delete(
        self,
        db: AsyncSession,
        *,
        id: int,
        commit: bool = True
    ) -> bool:
        """删除记录"""
        if not self.crud:
            raise NotImplementedError("Service 未配置 CRUD")

        result = await self.crud.delete(db, id=id, commit=commit)

        # 清除缓存
        await self.invalidate_cache(self._cache_key("id", id))

        return result is not None


class ServiceRegistry:
    """
    Service 注册表

    用于管理和获取 Service 实例，支持依赖注入

    使用示例:
        # 注册
        services = ServiceRegistry()
        services.register("user", UserService())

        # 获取
        user_service = services.get("user")
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._services = {}
        return cls._instance

    def register(self, name: str, service: BaseService) -> None:
        """注册 Service"""
        self._services[name] = service
        logger.debug("注册 Service: {}", name)

    def get(self, name: str) -> Optional[BaseService]:
        """获取 Service"""
        return self._services.get(name)

    def get_all(self) -> dict[str, BaseService]:
        """获取所有 Service"""
        return self._services.copy()


# 全局 Service 注册表
services = ServiceRegistry()
