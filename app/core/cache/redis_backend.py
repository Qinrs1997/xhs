"""Redis 后端实现

特点:
- 支持分布式部署
- 数据持久化
- 通过 `orjson`(若安装)或 `json` 做值的序列化
- 适合生产环境

懒加载 Redis 客户端: 首次调用 `_get_client()` 时建立连接并 ping, 后续复用。
"""
from __future__ import annotations

import json
from typing import Any

from app.core.logger import logger

from .base import CacheBackend


class RedisCache(CacheBackend):
    """Redis 缓存实现"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        prefix: str = "cache:",
        default_ttl: int = 300,
        **kwargs: Any,
    ):
        self._host = host
        self._port = port
        self._db = db
        self._password = password
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._kwargs = kwargs
        self._client: Any = None

    async def _get_client(self):
        """获取 Redis 客户端(懒加载)"""
        if self._client is None:
            try:
                import redis.asyncio as redis

                self._client = redis.Redis(
                    host=self._host,
                    port=self._port,
                    db=self._db,
                    password=self._password or None,
                    decode_responses=False,  # 我们自己处理序列化
                    **self._kwargs,
                )
                # 测试连接
                await self._client.ping()
                logger.info(
                    "Redis 连接成功: {}:{}/{}", self._host, self._port, self._db
                )
            except ImportError as exc:
                raise ImportError("请安装 redis: pip install redis") from exc
            except Exception as e:
                logger.error("Redis 连接失败: {}", e)
                raise
        return self._client

    def _make_key(self, key: str) -> str:
        """生成带前缀的 key"""
        return f"{self._prefix}{key}"

    def _serialize(self, value: Any) -> bytes:
        """序列化值(优先使用 orjson)"""
        try:
            import orjson

            return orjson.dumps(value, option=orjson.OPT_NON_STR_KEYS)
        except ImportError:
            return json.dumps(value, ensure_ascii=False, default=str).encode(
                "utf-8"
            )

    def _deserialize(self, data: bytes | None) -> Any:
        """反序列化值(优先使用 orjson)"""
        if data is None:
            return None
        try:
            import orjson

            return orjson.loads(data)
        except ImportError:
            return json.loads(data.decode("utf-8"))

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        data = await client.get(self._make_key(key))
        return self._deserialize(data)

    async def set(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        client = await self._get_client()
        effective_ttl = ttl if ttl is not None else self._default_ttl
        data = self._serialize(value)

        if effective_ttl > 0:
            await client.setex(self._make_key(key), effective_ttl, data)
        else:
            await client.set(self._make_key(key), data)
        return True

    async def set_if_not_exists(
        self, key: str, value: Any, ttl: int | None = None
    ) -> bool:
        """Redis 原生 `SET NX EX` — 多进程抢占时的原子锁"""
        client = await self._get_client()
        effective_ttl = ttl if ttl is not None else self._default_ttl
        data = self._serialize(value)
        if effective_ttl > 0:
            result = await client.set(
                self._make_key(key), data, nx=True, ex=effective_ttl
            )
        else:
            result = await client.set(self._make_key(key), data, nx=True)
        return bool(result)

    async def delete(self, key: str) -> bool:
        client = await self._get_client()
        result = await client.delete(self._make_key(key))
        return result > 0

    async def exists(self, key: str) -> bool:
        client = await self._get_client()
        return await client.exists(self._make_key(key)) > 0

    async def clear(self) -> bool:
        """清空当前前缀的所有缓存"""
        client = await self._get_client()
        keys = await client.keys(f"{self._prefix}*")
        if keys:
            await client.delete(*keys)
        return True

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        if not keys:
            return {}
        client = await self._get_client()
        full_keys = [self._make_key(k) for k in keys]
        values = await client.mget(full_keys)
        return {
            k: self._deserialize(v)
            for k, v in zip(keys, values, strict=False)
            if v is not None
        }

    async def set_many(
        self, mapping: dict[str, Any], ttl: int | None = None
    ) -> bool:
        client = await self._get_client()
        pipe = client.pipeline()
        effective_ttl = ttl if ttl is not None else self._default_ttl

        for key, value in mapping.items():
            full_key = self._make_key(key)
            data = self._serialize(value)
            if effective_ttl > 0:
                pipe.setex(full_key, effective_ttl, data)
            else:
                pipe.set(full_key, data)

        await pipe.execute()
        return True

    async def delete_many(self, keys: list[str]) -> int:
        if not keys:
            return 0
        client = await self._get_client()
        full_keys = [self._make_key(k) for k in keys]
        return await client.delete(*full_keys)

    async def keys(self, pattern: str = "*") -> list[str]:
        client = await self._get_client()
        full_pattern = self._make_key(pattern)
        keys = await client.keys(full_pattern)
        prefix_len = len(self._prefix)
        return [k.decode("utf-8")[prefix_len:] for k in keys]

    async def close(self):
        """关闭连接"""
        if self._client:
            await self._client.close()
            self._client = None

    def stats(self) -> dict:
        """获取缓存统计信息"""
        return {
            "type": "redis",
            "host": self._host,
            "port": self._port,
            "db": self._db,
            "prefix": self._prefix,
            "default_ttl": self._default_ttl,
        }


__all__ = ["RedisCache"]
