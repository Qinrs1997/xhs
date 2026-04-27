"""缓存抽象层 (拆分后聚合入口)

提供统一的缓存接口, 支持多种后端:
- Memory: 内存缓存(默认, 适合单机/开发)
- Redis: Redis 缓存(生产环境推荐)

子模块              职责
------------------- ----------------------------------------------
base.py             `CacheEntry` / `CacheBackend` 抽象基类
memory.py           `MemoryCache` 进程内 LRU + 16 分片锁
redis_backend.py    `RedisCache` 分布式缓存
facade.py           `Cache` 门面(按 settings.REDIS_ENABLED 选后端)
decorators.py       `@cached` 装饰器 + `_DEFAULT_EXCLUDE_ARGS`

原单文件 `cache.py` 的公共 API 通过 `__init__.py` 完整 re-export,
现有 `from app.core.cache import cache, cached, MemoryCache` 无需修改。

使用示例::

    from app.core.cache import cache, cached

    # 基本操作
    await cache.set("user:1", {"name": "张三"}, ttl=300)
    user = await cache.get("user:1")
    await cache.delete("user:1")

    # 装饰器缓存
    @cached(ttl=60, key_prefix="users")
    async def get_user(user_id: int):
        return await db.get(User, user_id)

    # 清除装饰器缓存
    await get_user.invalidate(user_id=1)
"""
from __future__ import annotations

from .base import CacheBackend, CacheEntry
from .decorators import cached
from .facade import Cache
from .memory import MemoryCache
from .redis_backend import RedisCache

# ==================== 全局缓存实例 ====================
cache = Cache()

__all__ = [
    "Cache",
    "CacheBackend",
    "CacheEntry",
    "MemoryCache",
    "RedisCache",
    "cache",
    "cached",
]
