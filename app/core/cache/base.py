"""缓存抽象基类与数据模型

`CacheEntry`: 内存缓存条目(值 + 过期时间)
`CacheBackend`: 所有后端统一实现的抽象接口
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    """缓存条目"""

    value: Any
    expire_at: float | None = None  # Unix 时间戳, None 表示永不过期

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expire_at is None:
            return False
        return time.time() > self.expire_at


class CacheBackend(ABC):
    """缓存后端抽象基类"""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """获取缓存"""

    @abstractmethod
    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """设置缓存"""

    async def set_if_not_exists(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """仅当 key 不存在时写入(用于分布式锁/首次抢占)

        默认实现基于 `exists` + `set`,非原子但对单后端的单节点 Redis 足够。
        Redis 后端会重写为原生 `SET NX EX` 原子操作。
        """
        if await self.exists(key):
            return False
        return await self.set(key, value, ttl)

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除缓存"""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """检查 key 是否存在"""

    @abstractmethod
    async def clear(self) -> bool:
        """清空所有缓存"""

    @abstractmethod
    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """批量获取"""

    @abstractmethod
    async def set_many(
        self, mapping: dict[str, Any], ttl: int | None = None
    ) -> bool:
        """批量设置"""

    @abstractmethod
    async def delete_many(self, keys: list[str]) -> int:
        """批量删除, 返回删除数量"""

    @abstractmethod
    async def keys(self, pattern: str = "*") -> list[str]:
        """获取匹配的 keys"""


__all__ = ["CacheBackend", "CacheEntry"]
