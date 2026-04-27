"""公告模型"""
from datetime import datetime
from typing import List
from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.models.base import BaseModel


class TargetType(str, enum.Enum):
    """公告发送范围类型"""
    ALL = "all"       # 所有人
    DEPT = "dept"     # 指定部门


class Announcement(BaseModel):
    """公告模型"""
    __tablename__ = "announcements"
    __table_args__ = (
        # 复合索引：常用查询 "已发布的公告按时间排序"
        Index("ix_announcements_published", "is_published", "published_at"),
        {"comment": "公告表"},
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="公告标题"
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="公告内容"
    )
    type: Mapped[str] = mapped_column(
        String(50),
        default="notice",
        nullable=False,
        comment="公告类型: notice(通知), emergency(紧急), update(更新), event(活动)"
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否发布"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="发布时间"
    )
    author_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="发布人ID"
    )
    author_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="发布人名称"
    )

    # 新增：发送范围
    target_type: Mapped[TargetType] = mapped_column(
        SQLEnum(TargetType),
        default=TargetType.ALL,
        nullable=False,
        index=True,
        comment="发送范围: all(所有人), dept(指定部门)"
    )

    # 关系：关联的部门
    target_departments = relationship(
        "AnnouncementDepartment",
        back_populates="announcement",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    @property
    def target_dept_ids(self) -> List[int]:
        """获取目标部门 ID 列表"""
        return [td.department_id for td in self.target_departments]


class AnnouncementDepartment(BaseModel):
    """
    公告-部门关联表

    用于存储公告的目标部门（当 target_type='dept' 时）
    """
    __tablename__ = "announcement_departments"
    __table_args__ = {"comment": "公告-部门关联表"}

    announcement_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="公告ID"
    )

    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="部门ID"
    )

    # 关系
    announcement = relationship(
        "Announcement",
        back_populates="target_departments"
    )

    department = relationship(
        "Department",
    )

