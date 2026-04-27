"""API 幂等性保护中间件

通过 X-Idempotency-Key 请求头实现写操作幂等性保护。

原理：
- 客户端为每个写请求生成唯一的 idempotency key（如 UUID）
- 服务端缓存该 key 对应的响应，在窗口期内重复请求直接返回缓存结果
- 防止网络抖动导致的重复创建

使用方法：
    # 1. 作为中间件（全局保护 POST/PUT/PATCH）
    from app.core.idempotency import IdempotencyMiddleware
    app.add_middleware(IdempotencyMiddleware)

    # 2. 客户端使用：
    fetch("/api/v1/users", {
        method: "POST",
        headers: {
            "X-Idempotency-Key": "550e8400-e29b-41d4-a716-446655440000",
            "Content-Type": "application/json"
        },
        body: JSON.stringify({...})
    })
"""
import base64
import time
import asyncio

from typing import Optional


from app.core.config import settings

from app.core.logger import logger

# 受保护的 HTTP 方法（只对写操作启用）
IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH"}

# 缓存窗口（秒）
IDEMPOTENCY_WINDOW = 300  # 5 分钟

# Redis 中存储幂等条目使用的 key 前缀
_REDIS_KEY_PREFIX = "idempotency:"


def _encode_entry(status_code: int, headers: list, body: bytes) -> dict:
    """把响应缓存条目序列化为 JSON/orjson 友好的 dict(用于 Redis 存储)"""
    return {
        "status": int(status_code),
        "headers": [
            [
                k.decode("latin-1") if isinstance(k, (bytes, bytearray)) else str(k),
                v.decode("latin-1") if isinstance(v, (bytes, bytearray)) else str(v),
            ]
            for k, v in headers
        ],
        "body_b64": base64.b64encode(body or b"").decode("ascii"),
    }


def _decode_entry(data: dict) -> tuple[int, list, bytes]:
    """反序列化 Redis 中的幂等条目"""
    status_code = int(data.get("status", 200))
    headers = [
        (
            k.encode("latin-1") if isinstance(k, str) else bytes(k),
            v.encode("latin-1") if isinstance(v, str) else bytes(v),
        )
        for k, v in data.get("headers", [])
    ]
    body_b64 = data.get("body_b64", "")
    body = base64.b64decode(body_b64) if body_b64 else b""
    return status_code, headers, body


class _IdempotencyStore:
    """幂等性存储

    - 默认使用进程内 dict(单 worker 语义正确)
    - 当 `settings.REDIS_ENABLED=True` 时,响应缓存转由 `app.core.cache.cache` 存储
      (跨 worker/跨进程一致,Redis 不可达时自动降级为内存)
    - `_processing` 并发锁仍保持进程内(避免引入分布式锁的复杂度)
    """

    def __init__(self):
        self._store: dict[str, tuple[int, list, bytes, float]] = {}
        self._processing: dict[str, asyncio.Event] = {}
        self._last_cleanup = time.time()

    # -------- 内部 Redis 读写(通过 cache 门面, 失败时抛出给调用方降级) --------

    def _redis_enabled(self) -> bool:
        return bool(settings.REDIS_ENABLED)

    async def _redis_get(self, key: str) -> Optional[tuple[int, list, bytes]]:
        from app.core.cache import cache

        data = await cache.get(_REDIS_KEY_PREFIX + key)
        if not isinstance(data, dict):
            return None
        return _decode_entry(data)

    async def _redis_set(
        self, key: str, status_code: int, headers: list, body: bytes, ttl: int
    ) -> None:
        from app.core.cache import cache

        await cache.set(
            _REDIS_KEY_PREFIX + key,
            _encode_entry(status_code, headers, body),
            ttl=ttl,
        )

    # -------- 对外接口 --------

    async def get(self, key: str) -> Optional[tuple[int, list, bytes]]:
        """获取缓存的响应(Redis-first,失败时走内存)"""
        if self._redis_enabled():
            try:
                cached = await self._redis_get(key)
                if cached is not None:
                    return cached
            except Exception as e:
                logger.debug("幂等性 Redis 读取失败,降级内存: {}", e)

        entry = self._store.get(key)
        if entry is None:
            return None
        status_code, headers, body, expire_at = entry
        if time.time() > expire_at:
            self._store.pop(key, None)
            return None
        return status_code, headers, body

    async def set(
        self,
        key: str,
        status_code: int,
        headers: list,
        body: bytes,
        ttl: int = IDEMPOTENCY_WINDOW,
    ) -> None:
        """缓存响应(Redis 可用时双写 Redis + 内存,以便同一 worker 后续不走 Redis)"""
        if self._redis_enabled():
            try:
                await self._redis_set(key, status_code, headers, body, ttl)
            except Exception as e:
                logger.warning("幂等性 Redis 写入失败,仅写内存: {}", e)

        self._store[key] = (status_code, headers, body, time.time() + ttl)
        await self._maybe_cleanup()

    async def is_processing(self, key: str) -> bool:
        """检查 key 是否正在处理中(进程内)"""
        return key in self._processing

    async def start_processing(self, key: str) -> None:
        """标记 key 为处理中"""
        self._processing[key] = asyncio.Event()

    async def finish_processing(self, key: str) -> None:
        """标记 key 处理完成"""
        event = self._processing.pop(key, None)
        if event:
            event.set()

    async def wait_for_processing(self, key: str, timeout: float = 30) -> bool:
        """等待 key 处理完成"""
        event = self._processing.get(key)
        if event is None:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _maybe_cleanup(self) -> None:
        """定期清理过期条目"""
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now

        expired = [k for k, v in self._store.items() if now > v[3]]
        for k in expired:
            del self._store[k]


# 全局存储实例
_store = _IdempotencyStore()


class IdempotencyMiddleware:
    """幂等性保护中间件（纯 ASGI 实现）

    对 POST/PUT/PATCH 请求，如果携带 X-Idempotency-Key 头：
    - 首次请求：正常执行并缓存响应
    - 重复请求：直接返回缓存的响应（不再执行业务逻辑）

    不携带 X-Idempotency-Key 的写请求不受影响。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # 只对写操作生效
        if method not in IDEMPOTENT_METHODS:
            await self.app(scope, receive, send)
            return

        # 提取 X-Idempotency-Key
        headers = dict(scope.get("headers", []))
        idempotency_key = headers.get(b"x-idempotency-key", b"").decode()

        if not idempotency_key:
            # 没有幂等 key，正常处理
            await self.app(scope, receive, send)
            return

        # 补充路径信息（同一个 key 在不同路径下应该是独立的）
        path = scope.get("path", "/")
        cache_key = f"{method}:{path}:{idempotency_key}"

        # 1. 检查是否有缓存的响应
        cached = await _store.get(cache_key)
        if cached is not None:
            status_code, resp_headers, body = cached
            logger.debug(
                "幂等性命中 | key={} path={}", idempotency_key[:16], path
            )
            # 返回缓存的响应 + 标记头
            resp_headers_list = list(resp_headers)
            resp_headers_list.append(
                (b"x-idempotent-replayed", b"true")
            )
            await send({
                "type": "http.response.start",
                "status": status_code,
                "headers": resp_headers_list,
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        # 2. 检查是否正在处理（并发重复请求）
        if await _store.is_processing(cache_key):
            # 等待处理完成
            completed = await _store.wait_for_processing(cache_key)
            if completed:
                cached = await _store.get(cache_key)
                if cached is not None:
                    status_code, resp_headers, body = cached
                    resp_headers_list = list(resp_headers)
                    resp_headers_list.append(
                        (b"x-idempotent-replayed", b"true")
                    )
                    await send({
                        "type": "http.response.start",
                        "status": status_code,
                        "headers": resp_headers_list,
                    })
                    await send({
                        "type": "http.response.body",
                        "body": body,
                    })
                    return

        # 3. 首次请求，执行并捕获响应
        await _store.start_processing(cache_key)

        captured_status = None
        captured_headers = []
        captured_body = b""

        async def capture_send(message):
            nonlocal captured_status, captured_headers, captured_body
            if message["type"] == "http.response.start":
                captured_status = message["status"]
                captured_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                captured_body += message.get("body", b"")
            await send(message)

        try:
            await self.app(scope, receive, capture_send)

            # 只缓存成功的响应（2xx/4xx），不缓存 5xx
            if captured_status is not None and captured_status < 500:
                await _store.set(
                    cache_key,
                    captured_status,
                    captured_headers,
                    captured_body,
                )
        finally:
            await _store.finish_processing(cache_key)
