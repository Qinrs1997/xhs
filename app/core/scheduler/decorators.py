"""定时任务装饰器

业务模块使用 `@scheduled_task(...)` 装饰 async/sync 函数,
被装饰的函数会记录调度配置到模块级 `_pending_tasks` 列表,
由 `register_pending_tasks()`(定义在 package `__init__.py`)统一注册到全局 scheduler。

这样设计的好处:
- 装饰器只做标记, 不直接依赖 `AsyncScheduler` 实例, 避免导入时副作用
- 注册时机由启动流程显式控制(通常在 FastAPI `lifespan` 中)
"""
from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from .models import TriggerType

# 待注册的任务列表(模块级全局, 跨文件共享)
_pending_tasks: list[Callable] = []


def scheduled_task(
    trigger: str | TriggerType,
    id: str | None = None,
    name: str | None = None,
    description: str = "",
    is_system: bool = False,
    **trigger_args: Any,
):
    """定时任务装饰器

    使用示例::

        @scheduled_task(trigger="cron", hour=2, minute=0, id="daily_cleanup")
        async def daily_cleanup():
            # 清理逻辑
            pass

        @scheduled_task(trigger="interval", minutes=30)
        async def periodic_sync():
            # 同步逻辑
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        # 标记为定时任务, 稍后由 register_pending_tasks() 注册
        wrapper._scheduled_task = True
        wrapper._scheduler_config = {
            "func": func,
            "trigger": trigger,
            "id": id or func.__name__,
            "name": name or func.__name__,
            "description": description,
            "is_system": is_system,
            "trigger_args": trigger_args,
        }

        _pending_tasks.append(wrapper)
        return wrapper

    return decorator


__all__ = ["_pending_tasks", "scheduled_task"]
