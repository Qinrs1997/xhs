"""搜索历史模型

存储用户的 AI 搜索记录及其与生成任务的关联。
"""
from typing import Optional, List
from sqlalchemy import String, Text, Integer, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class SearchHistory(BaseModel):
    """搜索历史记录

    存储每次 AI 搜索的查询、结果摘要、搜索来源等信息。
    通过 generated_tasks 关联查询由此搜索衍生的 XHS 任务。
    """
    __tablename__ = "search_history"

    # 用户关联
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="创建用户ID",
    )

    # 搜索查询
    query: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="搜索查询关键词",
    )

    # 摘要（前 200 字截断，用于列表展示）
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="摘要（前200字截断）",
    )

    # 完整摘要
    full_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="完整摘要内容",
    )

    # 搜索来源数量
    sources_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="搜索来源数量",
    )

    # 状态：completed / generating / failed
    status: Mapped[str] = mapped_column(
        String(20),
        default="completed",
        nullable=False,
        index=True,
        comment="状态: completed/generating/failed",
    )

    # 搜索结果 JSON（搜索来源列表）
    search_results: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="搜索结果列表 (JSON)",
    )

    # 元数据 JSON（model/latency/provider 等）
    # 注意：字段名不能用 metadata（SQLAlchemy 保留词）
    metadata_info: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="搜索元数据 (JSON): model/latency_ms/search_provider 等",
    )

    # ===== 关系 =====
    user = relationship("User", backref="search_histories", lazy="noload")
    generated_task_links: Mapped[List["SearchGeneratedTask"]] = relationship(
        "SearchGeneratedTask",
        back_populates="search_history",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    # ===== 表级索引 =====
    __table_args__ = (
        Index("idx_search_history_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<SearchHistory(id={self.id}, query='{self.query}', status={self.status})>"


class SearchGeneratedTask(BaseModel):
    """搜索记录与 XHS 任务的关联表

    记录从某次搜索衍生出的所有生成任务。
    """
    __tablename__ = "search_generated_tasks"

    # 搜索记录关联
    search_history_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("search_history.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="搜索历史记录ID",
    )

    # XHS 任务关联
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("xhs_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="XHS 任务ID",
    )

    # ===== 关系 =====
    search_history: Mapped["SearchHistory"] = relationship(
        "SearchHistory",
        back_populates="generated_task_links",
    )
    task = relationship("XHSTask", lazy="noload")

    def __repr__(self) -> str:
        return f"<SearchGeneratedTask(search_history_id={self.search_history_id}, task_id={self.task_id})>"
