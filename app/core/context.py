"""请求上下文模块

提供请求 ID 追踪、用户上下文等功能。
每个请求都会生成唯一的请求 ID，用于日志关联和问题排查。

使用方法：
    from app.core.context import get_request_id, get_current_user_id

    request_id = get_request_id()  # 获取当前请求 ID
    user_id = get_current_user_id()  # 获取当前用户 ID
"""
import uuid
from contextvars import ContextVar
from typing import Optional

# 请求上下文变量
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
_user_name_var: ContextVar[Optional[str]] = ContextVar("user_name", default=None)


def generate_request_id() -> str:
    """生成唯一请求 ID（32 字符 hex，比 UUID 字符串格式更快）"""
    return uuid.uuid4().hex


def set_request_id(request_id: Optional[str] = None) -> str:
    """
    设置当前请求 ID

    Args:
        request_id: 自定义请求 ID，如果不提供则自动生成

    Returns:
        当前请求 ID
    """
    if request_id is None:
        request_id = generate_request_id()
    _request_id_var.set(request_id)
    return request_id


def get_request_id() -> Optional[str]:
    """获取当前请求 ID"""
    return _request_id_var.get()


def clear_request_id() -> None:
    """清除当前请求 ID"""
    _request_id_var.set(None)


def set_current_user(user_id: int, user_name: Optional[str] = None) -> None:
    """
    设置当前用户信息（用于日志记录）

    Args:
        user_id: 用户 ID
        user_name: 用户名
    """
    _user_id_var.set(user_id)
    _user_name_var.set(user_name)


def get_current_user_id() -> Optional[int]:
    """获取当前用户 ID"""
    return _user_id_var.get()


def get_current_user_name() -> Optional[str]:
    """获取当前用户名"""
    return _user_name_var.get()


def clear_current_user() -> None:
    """清除当前用户信息"""
    _user_id_var.set(None)
    _user_name_var.set(None)


def clear_all_context() -> None:
    """清除所有上下文信息"""
    clear_request_id()
    clear_current_user()
