"""AsyncScheduler 调度引擎

纯 asyncio 实现的调度器核心, 管理:
- 任务注册/删除/暂停/恢复/立即执行
- 调度主循环 (`_run_scheduler`)
- 任务执行与日志记录 (`_execute_job`)
- 下次运行时间计算 (委托 `cron_parser`)
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.core.logger import logger

from .cron_parser import calculate_cron_next_run
from .models import JobExecutionLog, JobInfo, JobStatus, TriggerType


class AsyncScheduler:
    """异步任务调度器

    特点:
    - 纯 asyncio 实现, 无需 APScheduler 依赖
    - 支持 cron、interval、date 三种触发器
    - 任务状态持久化(可选)
    - 任务执行日志
    """

    def __init__(self):
        self._jobs: dict[str, JobInfo] = {}
        self._job_funcs: dict[str, Callable] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._execution_logs: list[JobExecutionLog] = []
        self._max_logs = 1000  # 最多保留的日志数
        self._started = False
        self._shutdown_event = asyncio.Event()
        self._scheduler_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        """调度器是否正在运行"""
        return self._started

    async def start(self):
        """启动调度器"""
        if self._started:
            logger.warning("调度器已经在运行")
            return

        self._started = True
        self._shutdown_event.clear()
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        logger.info(
            "定时任务调度器已启动, 已注册 {} 个任务", len(self._jobs)
        )

    async def shutdown(self, wait: bool = True):
        """关闭调度器"""
        if not self._started:
            return

        logger.info("正在关闭定时任务调度器...")
        self._started = False
        self._shutdown_event.set()

        if wait and self._running_tasks:
            logger.info("等待 {} 个任务完成...", len(self._running_tasks))
            await asyncio.gather(
                *self._running_tasks.values(), return_exceptions=True
            )

        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task

        logger.info("定时任务调度器已关闭")

    async def _run_scheduler(self):
        """调度器主循环"""
        while not self._shutdown_event.is_set():
            try:
                now = datetime.now()

                for job_id, job_info in list(self._jobs.items()):
                    if job_info.status == JobStatus.PAUSED:
                        continue

                    if (
                        job_info.next_run_time
                        and now >= job_info.next_run_time
                        and job_id not in self._running_tasks
                    ):
                        task = asyncio.create_task(self._execute_job(job_id))
                        self._running_tasks[job_id] = task
                        task.add_done_callback(
                            lambda t, jid=job_id: self._running_tasks.pop(jid, None)
                        )

                # 每秒检查一次
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("调度器循环异常: {}", e)
                await asyncio.sleep(5)

    async def _execute_job(self, job_id: str):
        """执行任务

        多 worker 场景下,每个 worker 都会各自起一个 scheduler 循环,
        直接执行会导致清理/补偿类任务重复跑(可能重复写统计、重复删数据)。
        因此在真正执行前,先用 `app.core.cache.cache.set_if_not_exists` 做一次
        "本次触发的抢占锁":只有抢到的 worker 执行,其它跳过。
        Key 带 `next_run_time`/`last_run_time` 的 epoch 秒,保证同一触发点唯一。
        """
        job_info = self._jobs.get(job_id)
        if not job_info:
            return

        job_func = self._job_funcs.get(job_id)
        if not job_func:
            logger.error("任务函数未找到: {}", job_id)
            return

        # 以当前"触发时间"为锁的一部分,同一时刻所有 worker 计算出的值一致;
        # 优先用 next_run_time(已触发,置空前的值),否则回落到当前 UTC 秒。
        trigger_ts = int(
            (job_info.next_run_time or datetime.now()).timestamp()
        )
        lock_key = f"scheduler:lock:{job_id}:{trigger_ts}"
        # 锁 TTL 取 5 分钟,足以让一次任务跑完又不会占用过久;长任务可在任务内续租
        try:
            from app.core.cache import cache

            acquired = await cache.set_if_not_exists(lock_key, "1", ttl=300)
        except Exception as e:
            # 缓存不可达时,降级为本进程独占执行(原行为),但记录 warning
            logger.warning(
                "调度锁检查失败,降级本地执行(存在多 worker 重复执行风险): {}", e
            )
            acquired = True

        if not acquired:
            logger.debug(
                "[Scheduler] 任务 {} 已被其他 worker 抢占执行,跳过", job_id
            )
            return

        log = JobExecutionLog(
            job_id=job_id,
            started_at=datetime.now(),
            status=JobStatus.RUNNING,
        )

        job_info.status = JobStatus.RUNNING
        job_info.last_run_time = datetime.now()

        try:
            logger.info("[Scheduler] 开始执行任务: {} ({})", job_info.name, job_id)

            if asyncio.iscoroutinefunction(job_func):
                result = await job_func()
            else:
                result = await asyncio.to_thread(job_func)

            log.status = JobStatus.COMPLETED
            log.result = str(result) if result else "success"
            job_info.status = JobStatus.PENDING
            job_info.last_result = log.result
            job_info.run_count += 1

            logger.info("[Scheduler] 任务完成: {} ({})", job_info.name, job_id)

        except Exception as e:
            log.status = JobStatus.FAILED
            log.error = str(e)
            job_info.status = JobStatus.PENDING
            job_info.last_result = f"ERROR: {e}"
            job_info.error_count += 1

            logger.exception("[Scheduler] 任务失败: {} ({})", job_info.name, job_id)

        finally:
            log.finished_at = datetime.now()
            log.duration_ms = (
                log.finished_at - log.started_at
            ).total_seconds() * 1000

            # 计算下次执行时间
            job_info.next_run_time = self._calculate_next_run_time(job_info)

            self._execution_logs.append(log)
            if len(self._execution_logs) > self._max_logs:
                self._execution_logs = self._execution_logs[-self._max_logs :]

    def _calculate_next_run_time(self, job_info: JobInfo) -> datetime | None:
        """计算下次执行时间"""
        now = datetime.now()
        trigger_args = job_info.trigger_args

        if job_info.trigger_type == TriggerType.INTERVAL:
            interval = timedelta(
                days=trigger_args.get("days", 0),
                hours=trigger_args.get("hours", 0),
                minutes=trigger_args.get("minutes", 0),
                seconds=trigger_args.get("seconds", 0),
            )
            return now + interval

        if job_info.trigger_type == TriggerType.CRON:
            return calculate_cron_next_run(trigger_args, now)

        if job_info.trigger_type == TriggerType.DATE:
            # 一次性任务, 执行后不再调度
            return None

        return None

    # ==================== 任务管理 API ====================

    async def add_job(
        self,
        func: Callable,
        trigger: str | TriggerType,
        id: str | None = None,
        name: str | None = None,
        description: str = "",
        replace_existing: bool = True,
        is_system: bool = False,
        **trigger_args: Any,
    ) -> JobInfo:
        """添加任务

        Args:
            func: 任务函数(同步或异步)
            trigger: 触发器类型 ("cron" / "interval" / "date")
            id: 任务 ID(省略时自动生成)
            name: 任务名称
            description: 任务描述
            replace_existing: 如果存在是否替换
            is_system: 是否为系统内置任务(不可删除)
            **trigger_args: 触发器参数

        Returns:
            JobInfo
        """
        job_id = id or str(uuid.uuid4())[:8]

        if job_id in self._jobs:
            if replace_existing:
                await self.remove_job(job_id)
            else:
                raise ValueError(f"任务 {job_id} 已存在")

        if isinstance(trigger, str):
            trigger = TriggerType(trigger)

        job_info = JobInfo(
            id=job_id,
            name=name or func.__name__,
            func_name=f"{func.__module__}.{func.__name__}",
            trigger_type=trigger,
            trigger_args=trigger_args,
            description=description,
            is_system=is_system,
        )

        # 计算首次执行时间
        if trigger == TriggerType.DATE:
            run_date = trigger_args.get("run_date")
            if isinstance(run_date, str):
                run_date = datetime.fromisoformat(run_date)
            job_info.next_run_time = run_date
        else:
            job_info.next_run_time = self._calculate_next_run_time(job_info)

        self._jobs[job_id] = job_info
        self._job_funcs[job_id] = func

        logger.info(
            "[Scheduler] 添加任务: {} ({}), 下次执行: {}",
            job_info.name,
            job_id,
            job_info.next_run_time,
        )
        return job_info

    async def remove_job(self, job_id: str) -> bool:
        """移除任务"""
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._job_funcs.pop(job_id, None)

            if job_id in self._running_tasks:
                self._running_tasks[job_id].cancel()

            logger.info("[Scheduler] 移除任务: {}", job_id)
            return True
        return False

    async def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        if job_id in self._jobs:
            self._jobs[job_id].status = JobStatus.PAUSED
            logger.info("[Scheduler] 暂停任务: {}", job_id)
            return True
        return False

    async def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        if job_id in self._jobs:
            job_info = self._jobs[job_id]
            job_info.status = JobStatus.PENDING
            job_info.next_run_time = self._calculate_next_run_time(job_info)
            logger.info("[Scheduler] 恢复任务: {}", job_id)
            return True
        return False

    async def update_job(
        self,
        job_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        trigger: str | TriggerType | None = None,
        trigger_args: dict | None = None,
    ) -> JobInfo | None:
        """修改任务配置

        支持修改: 名称、描述、触发类型、调度参数
        修改后自动重新计算下次执行时间。
        """
        job_info = self._jobs.get(job_id)
        if not job_info:
            return None

        if name is not None:
            job_info.name = name
        if description is not None:
            job_info.description = description

        if trigger is not None:
            if isinstance(trigger, str):
                trigger = TriggerType(trigger)
            job_info.trigger_type = trigger

        if trigger_args is not None:
            job_info.trigger_args = trigger_args

        if trigger is not None or trigger_args is not None:
            job_info.next_run_time = self._calculate_next_run_time(job_info)

        logger.info(
            "[Scheduler] 更新任务: {} ({}), 触发器: {}, 参数: {}, 下次执行: {}",
            job_info.name,
            job_id,
            job_info.trigger_type.value,
            job_info.trigger_args,
            job_info.next_run_time,
        )
        return job_info

    async def run_job_now(self, job_id: str) -> bool:
        """立即执行任务"""
        if job_id not in self._jobs:
            return False

        if job_id in self._running_tasks:
            logger.warning("任务 {} 正在执行中", job_id)
            return False

        task = asyncio.create_task(self._execute_job(job_id))
        self._running_tasks[job_id] = task
        task.add_done_callback(lambda t: self._running_tasks.pop(job_id, None))

        return True

    def get_job(self, job_id: str) -> JobInfo | None:
        """获取任务信息"""
        return self._jobs.get(job_id)

    def get_jobs(self) -> list[JobInfo]:
        """获取所有任务"""
        return list(self._jobs.values())

    def get_job_logs(
        self, job_id: str | None = None, limit: int = 50
    ) -> list[dict]:
        """获取任务执行日志"""
        logs = self._execution_logs
        if job_id:
            logs = [entry for entry in logs if entry.job_id == job_id]

        logs = sorted(logs, key=lambda x: x.started_at, reverse=True)[:limit]

        return [
            {
                "job_id": entry.job_id,
                "started_at": entry.started_at.isoformat(),
                "finished_at": (
                    entry.finished_at.isoformat() if entry.finished_at else None
                ),
                "status": entry.status.value,
                "result": entry.result,
                "error": entry.error,
                "duration_ms": entry.duration_ms,
            }
            for entry in logs
        ]

    def stats(self) -> dict:
        """获取调度器统计信息"""
        return {
            "is_running": self._started,
            "total_jobs": len(self._jobs),
            "running_jobs": len(self._running_tasks),
            "paused_jobs": sum(
                1 for j in self._jobs.values() if j.status == JobStatus.PAUSED
            ),
            "total_executions": sum(
                j.run_count for j in self._jobs.values()
            ),
            "total_errors": sum(j.error_count for j in self._jobs.values()),
        }


__all__ = ["AsyncScheduler"]
