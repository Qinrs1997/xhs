"""速率限制模块

提供 API 速率限制功能，支持：
- 基于内存的限流（单机模式）
- 基于 Redis 的限流（分布式模式，可选）
- 按 IP 地址限流
- 按用户 ID 限流
- 按 API 路径限流

使用方法：
    # 1. 作为路由依赖使用
    from app.core.rate_limit import RateLimiter, rate_limit

    @router.get("/api/data")
    async def get_data(
        request: Request,
        _: None = Depends(rate_limit(requests_per_minute=60))
    ):
        return {"data": "..."}

    # 2. 使用装饰器
    @router.get("/api/expensive")
    @rate_limit_decorator(requests_per_minute=10)
    async def expensive_operation():
        return {"result": "..."}

    # 3. 全局中间件方式
    from app.core.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""
import time
import asyncio

from typing import Optional, Dict, Callable
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import wraps

from fastapi import Request, HTTPException, status
from starlette.responses import JSONResponse

from app.core.config import settings

from app.core.logger import logger


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    requests_per_minute: int = 60  # 每分钟请求数
    burst_size: int = 10  # 突发请求数（令牌桶容量）
    window_seconds: int = 60  # 滑动窗口大小（秒）
    block_seconds: int = 60  # 超限后封锁时间（秒）
    key_prefix: str = "rl:"  # Redis key 前缀
    whitelist_paths: list = field(default_factory=lambda: [
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    ])
    whitelist_ips: list = field(default_factory=list)


class TokenBucket:
    """令牌桶算法实现"""

    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: 令牌生成速率（每秒）
            capacity: 桶容量（最大令牌数）
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_time = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """
        尝试获取令牌

        Args:
            tokens: 需要的令牌数

        Returns:
            是否成功获取
        """
        async with self._lock:
            now = time.time()
            # 计算这段时间内生成的令牌
            time_passed = now - self.last_time
            self.tokens = min(self.capacity, self.tokens + time_passed * self.rate)
            self.last_time = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def remaining(self) -> int:
        """剩余令牌数"""
        now = time.time()
        time_passed = now - self.last_time
        return int(min(self.capacity, self.tokens + time_passed * self.rate))


class SlidingWindowCounter:
    """滑动窗口计数器实现"""

    def __init__(self, window_seconds: int = 60, max_requests: int = 60):
        """
        Args:
            window_seconds: 窗口大小（秒）
            max_requests: 窗口内最大请求数
        """
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.requests: list = []  # [(timestamp, count), ...]
        self._lock = asyncio.Lock()

    async def is_allowed(self) -> tuple[bool, int, int]:
        """
        检查是否允许请求

        Returns:
            (是否允许, 剩余请求数, 重置时间戳)
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # 清理过期的请求记录
            self.requests = [
                (ts, count) for ts, count in self.requests
                if ts > window_start
            ]

            # 计算当前窗口内的请求数
            current_count = sum(count for _, count in self.requests)
            remaining = max(0, self.max_requests - current_count)
            reset_time = int(now + self.window_seconds)

            if current_count < self.max_requests:
                self.requests.append((now, 1))
                return True, remaining - 1, reset_time

            return False, 0, reset_time


class InMemoryRateLimiter:
    """
    基于内存的速率限制器（单机模式）

    改进：
    - _limiters 使用 OrderedDict 实现 LRU，超过 max_limiters 时淘汰最老的
    - cleanup() 主动清理窗口内无请求的限流器和过期封锁记录
    - is_allowed() 每 ~100 次调用概率触发 cleanup，避免手动调度
    """

    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
        max_limiters: int = 10000,
    ):
        self.config = config or RateLimitConfig()
        self._max_limiters = max_limiters
        # 使用 OrderedDict 实现 LRU，key -> SlidingWindowCounter
        self._limiters: OrderedDict[str, SlidingWindowCounter] = OrderedDict()
        # 封锁列表，key -> 解封时间戳
        self._blocked: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._call_count = 0  # 用于概率触发 cleanup
        # 持有 fire-and-forget cleanup task 的强引用，避免事件循环 GC 提前终止
        self._cleanup_tasks: set[asyncio.Task] = set()

    async def is_allowed(self, key: str) -> tuple[bool, dict]:
        """
        检查是否允许请求

        Args:
            key: 限流键（如 IP 地址、用户 ID）

        Returns:
            (是否允许, 限流信息字典)
        """
        now = time.time()

        # 概率触发 cleanup（约每 100 次调用一次）
        self._call_count += 1
        if self._call_count >= 100:
            self._call_count = 0
            task = asyncio.create_task(self.cleanup())
            self._cleanup_tasks.add(task)
            task.add_done_callback(self._cleanup_tasks.discard)

        # 检查是否在封锁列表中
        if key in self._blocked:
            if now < self._blocked[key]:
                retry_after = int(self._blocked[key] - now)
                return False, {
                    "remaining": 0,
                    "reset": int(self._blocked[key]),
                    "retry_after": retry_after,
                    "blocked": True,
                }
            else:
                # 解除封锁
                del self._blocked[key]

        # 获取或创建限流器
        async with self._lock:
            if key in self._limiters:
                # LRU：移到末尾表示最近使用
                self._limiters.move_to_end(key)
            else:
                # 淘汰最老的条目（如果超过上限）
                while len(self._limiters) >= self._max_limiters:
                    self._limiters.popitem(last=False)
                self._limiters[key] = SlidingWindowCounter(
                    window_seconds=self.config.window_seconds,
                    max_requests=self.config.requests_per_minute,
                )

        limiter = self._limiters[key]
        allowed, remaining, reset_time = await limiter.is_allowed()

        rate_info = {
            "remaining": remaining,
            "reset": reset_time,
            "limit": self.config.requests_per_minute,
        }

        if not allowed:
            # 超限，加入封锁列表
            block_until = now + self.config.block_seconds
            self._blocked[key] = block_until
            rate_info["retry_after"] = self.config.block_seconds
            rate_info["blocked"] = True

        return allowed, rate_info

    async def cleanup(self):
        """
        清理过期的限流器和封锁记录

        - 移除解封时间已过的封锁记录
        - 移除窗口内无请求记录的空闲限流器
        """
        now = time.time()
        async with self._lock:
            # 清理过期封锁
            expired_blocks = [
                key for key, until in self._blocked.items()
                if now > until
            ]
            for key in expired_blocks:
                del self._blocked[key]

            # 清理窗口内无请求记录的限流器
            stale_keys = []
            for key, counter in self._limiters.items():
                window_start = now - counter.window_seconds
                # 如果所有请求记录都已过期，说明这个限流器闲置了
                if not counter.requests or all(
                    ts <= window_start for ts, _ in counter.requests
                ):
                    stale_keys.append(key)
            for key in stale_keys:
                del self._limiters[key]

            if stale_keys or expired_blocks:
                logger.debug(
                    "限流清理 | 移除限流器={} 移除封锁={} 剩余限流器={}",
                    len(stale_keys), len(expired_blocks), len(self._limiters),
                )


# 全局限流器实例
_rate_limiter: Optional[InMemoryRateLimiter] = None


def get_rate_limiter() -> InMemoryRateLimiter:
    """获取全局限流器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        config = RateLimitConfig(
            requests_per_minute=settings.RATE_LIMIT_REQUESTS_PER_MINUTE,
            burst_size=settings.RATE_LIMIT_BURST_SIZE,
        )
        _rate_limiter = InMemoryRateLimiter(config)
    return _rate_limiter


# 从 utils 导入统一的 get_client_ip 函数
from app.core.utils import get_client_ip


# 缓存自定义限流器实例（按 requests_per_minute 分组）
_custom_limiters: Dict[int, InMemoryRateLimiter] = {}


def rate_limit(
    requests_per_minute: Optional[int] = None,
    key_func: Optional[Callable[[Request], str]] = None,
):
    """
    速率限制依赖

    Args:
        requests_per_minute: 每分钟请求数限制（覆盖全局配置）
        key_func: 自定义限流键生成函数，默认使用 IP 地址

    Returns:
        FastAPI 依赖函数

    使用示例：
        @router.get("/api/data")
        async def get_data(
            request: Request,
            _: None = Depends(rate_limit(requests_per_minute=60))
        ):
            return {"data": "..."}
    """
    async def dependency(request: Request) -> None:
        # 检查是否启用速率限制
        if not settings.RATE_LIMIT_ENABLED:
            return None

        # 获取限流键
        if key_func:
            key = key_func(request)
        else:
            key = f"ip:{get_client_ip(request)}"

        # 检查白名单
        limiter = get_rate_limiter()
        if request.url.path in limiter.config.whitelist_paths:
            return None

        # 使用自定义限流器或全局限流器
        if requests_per_minute:
            # 复用同配置的限流器实例（修复：之前每次请求都新建实例导致限流失效）
            if requests_per_minute not in _custom_limiters:
                _custom_limiters[requests_per_minute] = InMemoryRateLimiter(
                    RateLimitConfig(requests_per_minute=requests_per_minute)
                )
            allowed, rate_info = await _custom_limiters[requests_per_minute].is_allowed(key)
        else:
            allowed, rate_info = await limiter.is_allowed(key)

        if not allowed:
            logger.warning(
                "速率限制 | key={} path={} info={}",
                key, request.url.path, rate_info
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": 429,
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "请求过于频繁，请稍后再试",
                    "retry_after": rate_info.get("retry_after", 60),
                },
                headers={
                    "Retry-After": str(rate_info.get("retry_after", 60)),
                    "X-RateLimit-Limit": str(rate_info.get("limit", 60)),
                    "X-RateLimit-Remaining": str(rate_info.get("remaining", 0)),
                    "X-RateLimit-Reset": str(rate_info.get("reset", 0)),
                },
            )

        return None

    return dependency


def rate_limit_decorator(
    requests_per_minute: int = 60,
    key_func: Optional[Callable[[Request], str]] = None,
):
    """
    速率限制装饰器

    Args:
        requests_per_minute: 每分钟请求数限制
        key_func: 自定义限流键生成函数

    使用示例：
        @router.get("/api/expensive")
        @rate_limit_decorator(requests_per_minute=10)
        async def expensive_operation(request: Request):
            return {"result": "..."}
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 从参数中提取 request
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if request is None:
                request = kwargs.get("request")

            if request is None:
                # 无法获取 request，跳过限流
                return await func(*args, **kwargs)

            # 应用限流检查
            await rate_limit(requests_per_minute, key_func)(request)

            return await func(*args, **kwargs)
        return wrapper
    return decorator


class RateLimitMiddleware:
    """
    速率限制中间件（全局限流）

    使用纯 ASGI 接口实现，避免 BaseHTTPMiddleware 的问题。

    使用方法：
        from app.core.rate_limit import RateLimitMiddleware
        app.add_middleware(RateLimitMiddleware)
    """

    def __init__(self, app):
        self.app = app
        self.limiter = get_rate_limiter()

    async def __call__(self, scope, receive, send):
        """ASGI 接口入口"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 检查是否启用速率限制
        if not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # 检查白名单路径
        if path in self.limiter.config.whitelist_paths:
            await self.app(scope, receive, send)
            return

        # 获取客户端 IP
        headers = dict(scope.get("headers", []))
        client_ip = self._get_client_ip(scope, headers)
        key = f"ip:{client_ip}"

        # 检查限流
        allowed, rate_info = await self.limiter.is_allowed(key)

        if not allowed:
            logger.warning(
                "速率限制 | key={} path={} info={}",
                key, path, rate_info
            )
            # 返回 429 响应
            response = JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": "请求过于频繁，请稍后再试",
                    "retry_after": rate_info.get("retry_after", 60),
                },
                headers={
                    "Retry-After": str(rate_info.get("retry_after", 60)),
                    "X-RateLimit-Limit": str(rate_info.get("limit", 60)),
                    "X-RateLimit-Remaining": str(rate_info.get("remaining", 0)),
                    "X-RateLimit-Reset": str(rate_info.get("reset", 0)),
                },
            )
            await response(scope, receive, send)
            return

        # 添加限流响应头
        original_send = send

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                # 添加速率限制响应头
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"X-RateLimit-Limit", str(rate_info.get("limit", 60)).encode()),
                    (b"X-RateLimit-Remaining", str(rate_info.get("remaining", 0)).encode()),
                    (b"X-RateLimit-Reset", str(rate_info.get("reset", 0)).encode()),
                ])
                message = {**message, "headers": headers}
            await original_send(message)

        await self.app(scope, receive, send_with_headers)

    def _get_client_ip(self, scope: dict, headers: dict) -> str:
        """获取客户端 IP（使用统一函数）"""
        from app.core.utils import get_client_ip_from_scope
        return get_client_ip_from_scope(scope, headers)


# 导出
__all__ = [
    "InMemoryRateLimiter",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "get_client_ip",
    "get_rate_limiter",
    "rate_limit",
    "rate_limit_decorator",
]
