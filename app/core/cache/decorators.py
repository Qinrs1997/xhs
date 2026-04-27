"""缓存装饰器 `@cached`

基于 `inspect.signature` 提取函数参数名, 支持:
- 自动排除不可序列化的参数 (`db` / `session` / `request` / `response` / ...)
- 用户自定义 `exclude_args` 继续追加排除名单
- 自定义 `key_builder` 接管 key 生成
- 条件函数 `unless(result)` 决定是否缓存
- 附加 `invalidate(*args, **kwargs)` 方法清除指定入参的缓存
"""
from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

T = TypeVar("T")

# 默认排除的参数名(不可序列化 / 每次请求都不同, 不应纳入缓存 key)
_DEFAULT_EXCLUDE_ARGS: frozenset[str] = frozenset(
    {
        "db",
        "session",
        "request",
        "response",
        "background_tasks",
        "websocket",
    }
)


def _build_default_cache_key(
    prefix: str,
    func: Callable,
    args: tuple,
    kwargs: dict,
    exclude: frozenset[str],
) -> str:
    """根据函数签名构建稳定的缓存 key

    1. 用 `inspect.signature` 将 positional args 映射为参数名,
       然后统一按参数名过滤 exclude 集合。
    2. 对剩余参数做 `str()` 拼接 → MD5 摘要。
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    key_parts: list[str] = [prefix]

    # 处理 positional args - 跳过 self/cls 和 exclude 列表
    for idx, value in enumerate(args):
        name = params[idx] if idx < len(params) else f"_arg{idx}"
        if name in ("self", "cls") or name in exclude:
            continue
        key_parts.append(f"{name}={value}")

    # 处理 keyword args
    for k, v in sorted(kwargs.items()):
        if k in exclude:
            continue
        key_parts.append(f"{k}={v}")

    raw_key = ":".join(key_parts)
    # MD5 仅作缓存 key 摘要, 非安全哈希; usedforsecurity=False 明确声明非密码学用途
    digest = hashlib.md5(raw_key.encode(), usedforsecurity=False).hexdigest()
    return f"{prefix}:{digest[:16]}"


def cached(
    ttl: int = 300,
    key_prefix: str | None = None,
    key_builder: Callable[..., str] | None = None,
    unless: Callable[..., bool] | None = None,
    exclude_args: list[str] | None = None,
):
    """函数结果缓存装饰器

    Args:
        ttl: 缓存时间(秒)
        key_prefix: 缓存 key 前缀
        key_builder: 自定义 key 生成函数
        unless: 条件函数, 返回 True 时不缓存
        exclude_args: 额外需要排除的参数名列表(默认已排除 db/session/request 等)

    使用示例::

        @cached(ttl=60)
        async def get_user(user_id: int):
            return await db.get(User, user_id)

        # 装饰 Service 方法 (db 参数自动排除)
        @cached(ttl=120)
        async def get_user_credits(self, db: AsyncSession, user_id: int):
            ...

        # 自定义 key
        @cached(ttl=60, key_builder=lambda user_id, **kw: f"user:{user_id}")
        async def get_user(user_id: int):
            ...

        # 条件不缓存
        @cached(ttl=60, unless=lambda result: result is None)
        async def get_user(user_id: int):
            ...
    """
    final_exclude = _DEFAULT_EXCLUDE_ARGS | frozenset(exclude_args or [])

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        prefix = key_prefix or f"{func.__module__}.{func.__name__}"

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # 运行时导入 cache 实例, 避免 __init__.py 与 decorators.py 的循环导入
            from app.core.cache import cache

            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = _build_default_cache_key(
                    prefix, func, args, kwargs, final_exclude
                )

            cached_value = await cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            result = await func(*args, **kwargs)

            should_cache = True
            if unless and unless(result):
                should_cache = False

            if should_cache and result is not None:
                await cache.set(cache_key, result, ttl=ttl)

            return result

        async def invalidate(*args, **kwargs):
            """使缓存失效"""
            from app.core.cache import cache

            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = _build_default_cache_key(
                    prefix, func, args, kwargs, final_exclude
                )
            await cache.delete(cache_key)

        wrapper.invalidate = invalidate  # type: ignore[attr-defined]
        wrapper.cache_prefix = prefix  # type: ignore[attr-defined]

        return wrapper

    return decorator


__all__ = ["cached"]
