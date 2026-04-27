"""审计日志模型

记录敏感操作的审计日志，用于合规和安全审计。
只记录选择性的关键操作，不记录普通请求。
"""
from typing import Optional
from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.models.base import BaseModel


class AuditAction(str, enum.Enum):
    """审计操作类型"""
    # 用户相关
    USER_REGISTER = "user_register"      # 用户注册
    USER_LOGIN = "user_login"            # 用户登录
    USER_LOGOUT = "user_logout"          # 用户登出
    USER_DELETE = "user_delete"          # 用户删除
    USER_UPDATE = "user_update"          # 用户信息修改
    PASSWORD_CHANGE = "password_change"  # 密码修改
    PASSWORD_RESET = "password_reset"    # 密码重置

    # 权限相关
    ROLE_CREATE = "role_create"          # 角色创建
    ROLE_DELETE = "role_delete"          # 角色删除
    ROLE_ASSIGN = "role_assign"          # 角色分配
    ROLE_REMOVE = "role_remove"          # 角色移除
    PERMISSION_CHANGE = "permission_change"  # 权限变更

    # 部门相关
    DEPARTMENT_CREATE = "department_create"  # 部门创建
    DEPARTMENT_UPDATE = "department_update"  # 部门更新
    DEPARTMENT_DELETE = "department_delete"  # 部门删除
    DEPARTMENT_USER_ASSIGN = "department_user_assign"  # 部门成员分配
    DEPARTMENT_USER_REMOVE = "department_user_remove"  # 部门成员移除

    # 资金相关
    PAYMENT = "payment"                  # 支付
    REFUND = "refund"                    # 退款
    WITHDRAW = "withdraw"                # 提现
    RECHARGE = "recharge"                # 充值
    TRANSFER = "transfer"                # 转账

    # 数据相关
    DATA_EXPORT = "data_export"          # 数据导出
    DATA_IMPORT = "data_import"          # 数据导入
    DATA_DELETE = "data_delete"          # 数据删除（批量）

    # 系统相关
    CONFIG_CHANGE = "config_change"      # 配置修改
    SYSTEM_SETTING = "system_setting"    # 系统设置

    # 其他
    SENSITIVE_VIEW = "sensitive_view"    # 敏感数据查看
    CUSTOM = "custom"                    # 自定义操作


class AuditLevel(str, enum.Enum):
    """审计级别"""
    LOW = "low"           # 低敏感
    MEDIUM = "medium"     # 中敏感
    HIGH = "high"         # 高敏感
    CRITICAL = "critical" # 极高敏感


class AuditLog(BaseModel):
    """
    审计日志表

    记录敏感操作，用于安全审计和合规。
    """
    __tablename__ = "audit_logs"

    # 请求信息
    request_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="请求ID"
    )

    # 用户信息
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="操作用户ID"
    )
    username: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="操作用户名"
    )

    # 操作信息
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="操作类型"
    )
    level: Mapped[str] = mapped_column(
        String(20),
        default=AuditLevel.MEDIUM.value,
        nullable=False,
        comment="敏感级别"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="操作描述"
    )

    # 请求详情
    method: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="HTTP方法"
    )
    path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="请求路径"
    )
    ip: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="客户端IP"
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="客户端信息"
    )

    # 操作详情（JSON 格式）
    detail: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="操作详情(JSON)"
    )

    # 响应信息
    status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="响应状态码"
    )
    response_time: Mapped[Optional[float]] = mapped_column(
        nullable=True,
        comment="响应时间(ms)"
    )

    # 结果
    success: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="是否成功"
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="错误信息"
    )

    def __repr__(self) -> str:
        return (
            f"AuditLog(id={self.id}, action={self.action}, "
            f"user_id={self.user_id}, path={self.path})"
        )
