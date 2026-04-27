"""add search_history and search_generated_tasks

Revision ID: 20260318a001
Revises: dd5af39a69b3
Create Date: 2026-03-18 18:00:00.000000+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '20260318a001'
down_revision: Union[str, None] = 'dd5af39a69b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # 创建 search_history 表
    if "search_history" not in existing_tables:
        op.create_table(
            "search_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
            sa.Column("creator_id", sa.Integer(), nullable=True, comment="创建者ID"),
            sa.Column("updater_id", sa.Integer(), nullable=True, comment="更新者ID"),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="创建用户ID"),
            sa.Column("query", sa.String(500), nullable=False, comment="搜索查询关键词"),
            sa.Column("summary", sa.Text(), nullable=True, comment="摘要（前200字截断）"),
            sa.Column("full_summary", sa.Text(), nullable=True, comment="完整摘要内容"),
            sa.Column("sources_count", sa.Integer(), default=0, comment="搜索来源数量"),
            sa.Column("status", sa.String(20), nullable=False, server_default="completed", comment="状态: completed/generating/failed"),
            sa.Column("search_results", sa.JSON(), nullable=True, comment="搜索结果列表 (JSON)"),
            sa.Column("metadata_info", sa.JSON(), nullable=True, comment="搜索元数据 (JSON)"),
        )
        op.create_index("ix_search_history_user_id", "search_history", ["user_id"])
        op.create_index("ix_search_history_status", "search_history", ["status"])
        op.create_index("idx_search_history_user_status", "search_history", ["user_id", "status"])

    # 创建 search_generated_tasks 关联表
    if "search_generated_tasks" not in existing_tables:
        op.create_table(
            "search_generated_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, comment="主键ID"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="创建时间"),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, comment="更新时间"),
            sa.Column("creator_id", sa.Integer(), nullable=True, comment="创建者ID"),
            sa.Column("updater_id", sa.Integer(), nullable=True, comment="更新者ID"),
            sa.Column("search_history_id", sa.Integer(), sa.ForeignKey("search_history.id", ondelete="CASCADE"), nullable=False, comment="搜索历史记录ID"),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("xhs_tasks.id", ondelete="CASCADE"), nullable=False, comment="XHS 任务ID"),
        )
        op.create_index("ix_search_generated_tasks_search_history_id", "search_generated_tasks", ["search_history_id"])
        op.create_index("ix_search_generated_tasks_task_id", "search_generated_tasks", ["task_id"])


def downgrade() -> None:
    op.drop_table("search_generated_tasks")
    op.drop_table("search_history")
