"""Cron 表达式字段展开与下次运行时间计算

纯函数实现, 无 I/O 副作用, 便于独立单元测试。
支持语法: `*`, `N`, `N,M`, `N-M`, `*/N`, `N-M/S`。

拆自原 `scheduler.py` 中的 `AsyncScheduler._expand_cron_field` 和
`AsyncScheduler._calculate_cron_next_run` 两个方法, 逻辑保持一致。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.logger import logger


def expand_cron_field(spec: str, min_val: int, max_val: int) -> set[int]:
    """展开 cron 字段为数值集合。

    支持: `*`, `N`, `N,M`, `N-M`, `*/N`, `N-M/S`
    """
    result: set[int] = set()

    for raw_part in spec.split(","):
        part = raw_part.strip()
        if part == "*":
            result.update(range(min_val, max_val + 1))
        elif "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
            if range_part == "*":
                start, end = min_val, max_val
            elif "-" in range_part:
                start, end = map(int, range_part.split("-", 1))
            else:
                start, end = int(range_part), max_val
            result.update(range(start, end + 1, step))
        elif "-" in part:
            start, end = map(int, part.split("-", 1))
            result.update(range(start, end + 1))
        else:
            result.add(int(part))

    return {v for v in result if min_val <= v <= max_val}


def calculate_cron_next_run(trigger_args: dict, now: datetime) -> datetime:
    """计算 Cron 表达式的下次运行时间。

    支持两种传参方式:
      1. 关键字参数(兼容旧代码):
         `{"hour": 2, "minute": 0}`
         `{"hour": "*/2", "minute": "0,30"}`
      2. 标准 5 段 cron 表达式:
         `{"cron_expr": "*/5 * * * *"}`
         格式: 分 时 日 月 星期
    """
    cron_expr = trigger_args.get("cron_expr")
    if cron_expr:
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            logger.warning("无效的 cron 表达式: {}, 使用明天 00:00", cron_expr)
            return now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
        minute_spec, hour_spec, dom_spec, month_spec, dow_spec = parts
    else:
        minute_spec = str(trigger_args.get("minute", "0"))
        hour_spec = str(trigger_args.get("hour", "*"))
        dom_spec = str(trigger_args.get("day", "*"))
        month_spec = str(trigger_args.get("month", "*"))
        dow_spec = str(trigger_args.get("day_of_week", "*"))

    minutes = expand_cron_field(minute_spec, 0, 59)
    hours = expand_cron_field(hour_spec, 0, 23)
    doms = expand_cron_field(dom_spec, 1, 31)
    months = expand_cron_field(month_spec, 1, 12)
    dows = expand_cron_field(dow_spec, 0, 6)  # 0=周一 ... 6=周日

    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_check = now + timedelta(days=366)

    while candidate < max_check:
        if (
            candidate.month in months
            and candidate.day in doms
            and candidate.weekday() in dows
            and candidate.hour in hours
            and candidate.minute in minutes
        ):
            return candidate
        candidate += timedelta(minutes=1)

    logger.warning("Cron 未能在 366 天内找到匹配时间, 使用明天 00:00")
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


__all__ = ["calculate_cron_next_run", "expand_cron_field"]
