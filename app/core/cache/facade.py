"""`Cache` 门面类

根据 `settings.REDIS_ENABLED` 选择具体后端, 对外只暴露统一 API。
所有调用都通过 `_ensure_initialized()` 延迟初始化, 避免模块导入时触发 Redis 连接。
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logger import logger

from .base import CacheBackend
from .memory import MemoryCache
from .redis_backend import RedisCache


class Cache:
    """缓存管理器 (门面模式)

    根据配置自动选择后端, 提供统一的访问接口。
    """

    def __init__(self):
        self._backend: CacheBackend | None = None
        self._initialized = False

    def _ensure_initialized(self) -> CacheBackend:
        """确保已初始化"""
        if not self._initialized:
            self._initialize()
        return self._backend  # type: ignore[return-value]

    def _initialize(self):
        """根据配置初始化缓存后端"""
        if settings.REDIS_ENABLED:
            try:
                self._backend = RedisCache(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    password=(
                        settings.REDIS_PASSWORD
                        if settings.REDIS_PASSWORD
                        else None
                    ),
                    prefix=f"{settings.PROJECT_NAME}:cache:",
                )
                logger.info("缓存后端: Redis")
            except Exception as e:
                logger.warning("Redis 初始化失败, 降级到内存缓存: {}", e)
                self._backend = MemoryCache()
        else:
            self._backend = MemoryCache()
            logger.info("缓存后端: Memory")

        self._initialized = True

    # ==================== 代理方法 ====================

    async def get(self, key: str) -> Any | None:
        """获取缓存"""
        return await self._ensure_initialized().get(key)

    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """设置缓存"""
        return await self._ensure_initialized().set(key, value, ttl)

    async def set_if_not_exists(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """原子 SETNX(分布式锁首选);Redis 后端为原生 `SET NX EX`,Memory 为分片锁内 check-then-set"""
        return await self._ensure_initialized().set_if_not_exists(key, value, ttl)

    async def delete(self, key: str) -> bool:
        """删除缓存"""
        return await self._ensure_initialized().delete(key)

    async def exists(self, key: str) -> bool:
        """检查 key 是否存在"""
        return await self._ensure_initialized().exists(key)

    async def clear(self) -> bool:
        """清空所有缓存"""
        return await self._ensure_initialized().clear()

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """批量获取"""
        return await self._ensure_initialized().get_many(keys)

    async def set_many(
        self, mapping: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """批量设置"""
        return await self._ensure_initialized().set_many(mapping, ttl)

    async def delete_many(self, keys: list[str]) -> int:
        """批量删除"""
        return await self._ensure_initialized().delete_many(keys)

    async def keys(self, pattern: str = "*") -> list[str]:
        """获取匹配的 keys"""
        return await self._ensure_initialized().keys(pattern)

    async def close(self):
        """关闭缓存连接"""
        if self._initialized and hasattr(self._backend, "close"):
            await self._backend.close()  # type: ignore[attr-defined]

    def stats(self) -> dict:
        """获取统计信息"""
        backend = self._ensure_initialized()
        if hasattr(backend, "stats"):
            return backend.stats()  # type: ignore[attr-defined]
        return {"type": "unknown"}


__all__ = ["Cache"]
