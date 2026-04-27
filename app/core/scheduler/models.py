"""调度器数据模型

定义任务状态、触发器类型, 以及任务信息/执行日志的 dataclass。
从原单文件 `scheduler.py` 拆出, 无运行时依赖, 方便被 engine / decorators / tests 共享。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"  # 等待执行
    RUNNING = "running"  # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    PAUSED = "paused"  # 已暂停


class TriggerType(str, Enum):
    """触发器类型"""

    CRON = "cron"  # Cron 表达式
    INTERVAL = "interval"  # 间隔执行
    DATE = "date"  # 指定时间执行一次


@dataclass
class JobInfo:
    """任务信息"""

    id: str
    name: str
    func_name: str
    trigger_type: TriggerType
    trigger_args: dict
    status: JobStatus = JobStatus.PENDING
    next_run_time: datetime | None = None
    last_run_time: datetime | None = None
    last_result: str | None = None
    run_count: int = 0
    error_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    description: str = ""
    is_system: bool = False  # 系统内置任务标记(不可删除)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "func_name": self.func_name,
            "trigger_type": self.trigger_type.value,
            "trigger_args": self.trigger_args,
            "status": self.status.value,
            "next_run_time": (
                self.next_run_time.isoformat() if self.next_run_time else None
            ),
            "last_run_time": (
                self.last_run_time.isoformat() if self.last_run_time else None
            ),
            "last_result": self.last_result,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "created_at": self.created_at.isoformat(),
            "description": self.description,
            "is_system": self.is_system,
        }


@dataclass
class JobExecutionLog:
    """任务执行日志"""

    job_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: JobStatus = JobStatus.RUNNING
    result: str | None = None
    error: str | None = None
    duration_ms: float | None = None


__all__ = ["JobExecutionLog", "JobInfo", "JobStatus", "TriggerType"]
