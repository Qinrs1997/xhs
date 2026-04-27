"""XHS 任务模型

存储小红书内容生成任务的历史记录。
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Integer, Enum as SQLEnum, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import BaseModel


class TaskStatus(str, enum.Enum):
    """任务状态枚举"""
    DRAFT = "draft"           # 草稿
    PENDING = "pending"       # 待处理
    GENERATING = "generating" # 生成中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


class XHSTask(BaseModel):
    """
    XHS 任务模型

    存储小红书内容生成任务，包括主题、页面内容、状态等。
    """
    __tablename__ = "xhs_tasks"
    __table_args__ = (
        Index("ix_xhs_tasks_user_updated", "user_id", "updated_at"),
        Index("ix_xhs_tasks_user_status", "user_id", "status"),
    )

    # 用户关联
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="创建用户ID"
    )

    # 任务基本信息
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="任务标题"
    )
    topic: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="主题/话题内容"
    )

    # 任务状态
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus),
        default=TaskStatus.DRAFT,
        nullable=False,
        index=True,
        comment="任务状态"
    )

    # 页面内容 (JSON 数组)
    # 格式: [{"page_num": 1, "content": "...", "image_url": "...", ...}, ...]
    pages: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="页面内容列表 (JSON)"
    )

    # 生成参数
    style: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="风格类型"
    )
    model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="使用的 AI 模型"
    )

    # 模板关联
    template_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="使用的模板 ID"
    )

    # 文案数据（1:1 关系，直接存 JSON）
    # 格式: {"title": "...", "content": "...", "tags": [...], "emoji_title": "..."}
    copywriting: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="生成的发布文案 (JSON)"
    )

    # 统计信息
    page_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="页面数量"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="消耗的 Token 数"
    )

    # 错误信息（失败时记录）
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息"
    )

    # 完成时间
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="完成时间"
    )

    # 自动保存时间
    last_autosave_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="最后自动保存时间"
    )

    # 关系（noload: 避免列表查询时每个任务都自动 JOIN users 表）
    user = relationship("User", backref="xhs_tasks", lazy="noload")
    search_task_links = relationship(
        "SearchGeneratedTask",
        foreign_keys="SearchGeneratedTask.task_id",
        lazy="noload",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<XHSTask(id={self.id}, title='{self.title}', status={self.status})>"

