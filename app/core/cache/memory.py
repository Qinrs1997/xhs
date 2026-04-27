"""进程内内存缓存 (16 分片锁 + LRU + TTL)

特点:
- 16 个分片, 每片独立 `asyncio.Lock` 降低锁竞争
- 每个分片内部 `OrderedDict` + `move_to_end` 实现 LRU
- 写入时若分片已满, 按 LRU 淘汰最旧项
- 读取 / 存在性检查同时清理过期项

适用场景: 单机 / 开发 / 测试; 多进程部署下各进程独立缓存。
"""
from __future__ import annotations

import asyncio
import fnmatch
import time
from collections import OrderedDict
from typing import Any

from .base import CacheBackend, CacheEntry


class MemoryCache(CacheBackend):
    """内存缓存实现 (分片锁版本)"""

    _NUM_SHARDS = 16

    def __init__(self, max_size: int = 10000, default_ttl: int = 300):
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._shard_size = max_size // self._NUM_SHARDS
        self._shards: list[OrderedDict[str, CacheEntry]] = [
            OrderedDict() for _ in range(self._NUM_SHARDS)
        ]
        self._locks: list[asyncio.Lock] = [
            asyncio.Lock() for _ in range(self._NUM_SHARDS)
        ]

    def _shard_for(self, key: str) -> int:
        return hash(key) % self._NUM_SHARDS

    async def get(self, key: str) -> Any | None:
        idx = self._shard_for(key)
        async with self._locks[idx]:
            shard = self._shards[idx]
            entry = shard.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del shard[key]
                return None
            shard.move_to_end(key)
            return entry.value

    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        idx = self._shard_for(key)
        async with self._locks[idx]:
            shard = self._shards[idx]
            effective_ttl = ttl if ttl is not None else self._default_ttl
            expire_at = (
                time.time() + effective_ttl if effective_ttl > 0 else None
            )
            if key in shard:
                del shard[key]
            while len(shard) >= self._shard_size:
                shard.popitem(last=False)
            shard[key] = CacheEntry(value=value, expire_at=expire_at)
            return True

    async def set_if_not_exists(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """原子 SETNX(分片锁内完成,进程内语义正确;多进程无效需走 Redis)"""
        idx = self._shard_for(key)
        async with self._locks[idx]:
            shard = self._shards[idx]
            existing = shard.get(key)
            if existing is not None and not existing.is_expired():
                return False
            effective_ttl = ttl if ttl is not None else self._default_ttl
            expire_at = (
                time.time() + effective_ttl if effective_ttl > 0 else None
            )
            if key in shard:
                del shard[key]
            while len(shard) >= self._shard_size:
                shard.popitem(last=False)
            shard[key] = CacheEntry(value=value, expire_at=expire_at)
            return True

    async def delete(self, key: str) -> bool:
        idx = self._shard_for(key)
        async with self._locks[idx]:
            shard = self._shards[idx]
            if key in shard:
                del shard[key]
                return True
            return False

    async def exists(self, key: str) -> bool:
        idx = self._shard_for(key)
        async with self._locks[idx]:
            shard = self._shards[idx]
            entry = shard.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del shard[key]
                return False
            return True

    async def clear(self) -> bool:
        for idx in range(self._NUM_SHARDS):
            async with self._locks[idx]:
                self._shards[idx].clear()
        return True

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        groups: dict[int, list[str]] = {}
        for key in keys:
            groups.setdefault(self._shard_for(key), []).append(key)
        result: dict[str, Any] = {}
        for idx, shard_keys in groups.items():
            async with self._locks[idx]:
                shard = self._shards[idx]
                for key in shard_keys:
                    entry = shard.get(key)
                    if entry is None:
                        continue
                    if entry.is_expired():
                        del shard[key]
                        continue
                    shard.move_to_end(key)
                    result[key] = entry.value
        return result

    async def set_many(
        self, mapping: dict[str, Any], ttl: int | None = None
    ) -> bool:
        groups: dict[int, list[tuple[str, Any]]] = {}
        for key, value in mapping.items():
            groups.setdefault(self._shard_for(key), []).append((key, value))
        effective_ttl = ttl if ttl is not None else self._default_ttl
        expire_at = (
            time.time() + effective_ttl if effective_ttl > 0 else None
        )
        for idx, items in groups.items():
            async with self._locks[idx]:
                shard = self._shards[idx]
                for key, value in items:
                    if key in shard:
                        del shard[key]
                    while len(shard) >= self._shard_size:
                        shard.popitem(last=False)
                    shard[key] = CacheEntry(value=value, expire_at=expire_at)
        return True

    async def delete_many(self, keys: list[str]) -> int:
        groups: dict[int, list[str]] = {}
        for key in keys:
            groups.setdefault(self._shard_for(key), []).append(key)
        count = 0
        for idx, shard_keys in groups.items():
            async with self._locks[idx]:
                shard = self._shards[idx]
                for key in shard_keys:
                    if key in shard:
                        del shard[key]
                        count += 1
        return count

    async def keys(self, pattern: str = "*") -> list[str]:
        all_keys: list[str] = []
        for idx in range(self._NUM_SHARDS):
            async with self._locks[idx]:
                shard = self._shards[idx]
                expired = [k for k, v in shard.items() if v.is_expired()]
                for k in expired:
                    del shard[k]
                if pattern == "*":
                    all_keys.extend(shard.keys())
                else:
                    all_keys.extend(
                        k for k in shard if fnmatch.fnmatch(k, pattern)
                    )
        return all_keys

    def stats(self) -> dict:
        total = sum(len(s) for s in self._shards)
        return {
            "type": "memory",
            "size": total,
            "max_size": self._max_size,
            "shards": self._NUM_SHARDS,
            "default_ttl": self._default_ttl,
        }


__all__ = ["MemoryCache"]
