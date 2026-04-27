"""时区处理工具模块

提供统一的时区处理函数，所有数据库时间统一使用 UTC。

使用规范:
- 数据库存储: 统一使用 UTC 时间
- 前端显示: 根据用户时区转换为本地时间
- 后端处理: 尽量使用 UTC，避免时区歧义
"""
from datetime import datetime, timezone
from typing import Optional

# 默认时区（可根据用户设置调整）
DEFAULT_TIMEZONE = "Asia/Shanghai"


def now_utc() -> datetime:
    """
    获取当前 UTC 时间（带时区信息）

    Returns:
        datetime: 当前 UTC 时间

    Example:
        >>> now = now_utc()
        >>> print(now)  # 2024-01-06 04:12:55+00:00
    """
    return datetime.now(timezone.utc)


def now_local(tz: str = DEFAULT_TIMEZONE) -> datetime:
    """
    获取当前本地时间（带时区信息）

    Args:
        tz: 时区名称（如: Asia/Shanghai, America/New_York）

    Returns:
        datetime: 当前本地时间

    Example:
        >>> now = now_local("Asia/Shanghai")
        >>> print(now)  # 2024-01-06 12:12:55+08:00
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz))
    except ImportError:
        # Python < 3.9, 使用 pytz 或返回 UTC
        import warnings
        warnings.warn("zoneinfo not available, using UTC", stacklevel=2)
        return now_utc()


def to_utc(dt: datetime) -> datetime:
    """
    将本地时间转换为 UTC 时间

    Args:
        dt: 本地时间（可以是 naive 或 aware）

    Returns:
        datetime: UTC 时间

    Example:
        >>> local_time = datetime(2024, 1, 6, 12, 0, 0)
        >>> utc_time = to_utc(local_time)
    """
    if dt.tzinfo is None:
        # naive datetime，假设为 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime, tz: str = DEFAULT_TIMEZONE) -> datetime:
    """
    将 UTC 时间转换为本地时间

    Args:
        dt: UTC 时间
        tz: 目标时区名称

    Returns:
        datetime: 本地时间

    Example:
        >>> utc_time = now_utc()
        >>> local_time = to_local(utc_time, "Asia/Shanghai")
    """
    try:
        from zoneinfo import ZoneInfo
        if dt.tzinfo is None:
            # naive datetime，假设为 UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(tz))
    except ImportError:
        import warnings
        warnings.warn("zoneinfo not available, returning UTC", stacklevel=2)
        return to_utc(dt)


def format_datetime(
    dt: datetime,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    tz: Optional[str] = None
) -> str:
    """
    格式化时间（可选时区转换）

    Args:
        dt: 时间对象
        fmt: 格式化字符串
        tz: 目标时区（None 则使用原时区）

    Returns:
        str: 格式化后的时间字符串

    Example:
        >>> dt = now_utc()
        >>> print(format_datetime(dt, tz="Asia/Shanghai"))
        2024-01-06 12:12:55
    """
    if tz:
        dt = to_local(dt, tz)
    return dt.strftime(fmt)


def parse_datetime(
    dt_str: str,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    tz: str = DEFAULT_TIMEZONE
) -> datetime:
    """
    解析时间字符串为 UTC 时间

    Args:
        dt_str: 时间字符串
        fmt: 时间格式
        tz: 输入时间的时区（默认为本地时区）

    Returns:
        datetime: UTC 时间

    Example:
        >>> dt = parse_datetime("2024-01-06 12:00:00")
        >>> print(dt)  # UTC 时间
    """
    dt = datetime.strptime(dt_str, fmt)
    try:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    except ImportError:
        dt = dt.replace(tzinfo=timezone.utc)
    return to_utc(dt)
