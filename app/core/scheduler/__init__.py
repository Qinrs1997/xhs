"""定时任务调度器(拆分后聚合入口)

基于纯 asyncio 的异步调度系统, 支持:
- Cron 表达式任务
- 间隔任务
- 一次性任务
- 任务执行日志与统计

子模块               职责
-------------------  -----------------------------------------------
models.py            JobStatus / TriggerType / JobInfo / JobExecutionLog
cron_parser.py       纯函数: 展开 cron 字段 + 计算下次运行时间
engine.py            AsyncScheduler 主类(任务管理 + 调度主循环)
decorators.py        @scheduled_task 装饰器 + _pending_tasks 列表

原单文件 `scheduler.py` 的公共 API 通过本 `__init__.py` 完整 re-export,
现有 `from app.core.scheduler import scheduler, scheduled_task, ...` 无需修改。

使用示例::

    from app.core.scheduler import scheduler, scheduled_task

    # 方式 1: 装饰器定义任务
    @scheduled_task(trigger="cron", hour=2, minute=0, id="daily_cleanup")
    async def daily_cleanup():
        ...

    # 方式 2: 动态添加任务
    await scheduler.add_job(
        func=some_async_func,
        trigger="interval",
        minutes=30,
        id="my_task",
    )

    # 启动调度器(在 main.py 的 lifespan 中)
    await scheduler.start()
"""
from __future__ import annotations

from .decorators import _pending_tasks, scheduled_task
from .engine import AsyncScheduler
from .models import JobExecutionLog, JobInfo, JobStatus, TriggerType

# ==================== 全局调度器实例 ====================
scheduler = AsyncScheduler()


async def register_pending_tasks() -> None:
    """注册所有由 `@scheduled_task` 标记的待注册任务到全局 scheduler。

    通常在应用启动阶段(FastAPI `lifespan`)调用一次。
    """
    for task_func in _pending_tasks:
        config = task_func._scheduler_config
        await scheduler.add_job(
            func=config["func"],
            trigger=config["trigger"],
            id=config["id"],
            name=config["name"],
            description=config["description"],
            is_system=config.get("is_system", False),
            **config["trigger_args"],
        )
    _pending_tasks.clear()


__all__ = [
    "AsyncScheduler",
    "JobExecutionLog",
    "JobInfo",
    "JobStatus",
    "TriggerType",
    "register_pending_tasks",
    "scheduled_task",
    "scheduler",
]
