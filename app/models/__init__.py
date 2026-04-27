"""数据库模型

提供两种基础模型：
- BaseModel: 标准模型（id, created_at, updated_at）
- SoftDeleteModel: 软删除模型（额外 is_deleted, deleted_at）

使用示例：
    # 标准模型
    class User(BaseModel):
        __tablename__ = "users"
        username: Mapped[str] = mapped_column(String(50))

    # 软删除模型
    class Article(SoftDeleteModel):
        __tablename__ = "articles"
        title: Mapped[str] = mapped_column(String(200))
"""
from app.models.base import Base, BaseModel, SoftDeleteModel
from app.models.user import User
from app.models.role import Role, UserRole
from app.models.department import Department, UserDepartment
from app.models.audit_log import AuditLog, AuditAction, AuditLevel
from app.models.announcement import Announcement, AnnouncementDepartment, TargetType
from app.models.ai import AIPrompt, AIConversation, AIMessage, AIProvider, AIUsageLog, AISettings
from app.models.prompt import UserPrompt
from app.models.xhs_task import XHSTask, TaskStatus as XHSTaskStatus
from app.models.xhs_template import XHSTemplate
from app.models.membership import (
    MembershipPlan, CreditTransaction, CreditPack, CheckinRecord, Order, InviteRecord,
)
from app.models.search_history import SearchHistory, SearchGeneratedTask

__all__ = [
    "AIConversation",
    "AIMessage",
    # AI 增强功能
    "AIPrompt",
    "AIProvider",
    "AISettings",
    "AIUsageLog",
    # 公告
    "Announcement",
    "AnnouncementDepartment",
    "AuditAction",
    "AuditLevel",
    # 审计日志
    "AuditLog",
    # 基类
    "Base",
    "BaseModel",
    "CheckinRecord",
    "CreditPack",
    "CreditTransaction",
    # 部门
    "Department",
    "InviteRecord",
    # 会员 + 积分
    "MembershipPlan",
    "Order",
    "Role",
    "SearchGeneratedTask",
    # 搜索历史
    "SearchHistory",
    "SoftDeleteModel",
    "TargetType",
    # 业务模型
    "User",
    "UserDepartment",
    # 用户提示词
    "UserPrompt",
    "UserRole",
    # XHS
    "XHSTask",
    "XHSTaskStatus",
    "XHSTemplate",
]

