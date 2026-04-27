"""add composite indexes 2026-04

7 个业务高频查询的复合索引,覆盖:
- xhs_tasks: ix_xhs_tasks_user_updated / ix_xhs_tasks_user_status
- credit_transactions: idx_ct_user_type / idx_ct_user_created
- invite_records: idx_ir_inviter_created / idx_ir_ip_created
- announcements: ix_announcements_published

说明:
- 老库 create_all 已经建过的索引,本迁移通过 inspector 幂等跳过
- 新库在 alembic stamp head 前已由 create_all 建好,本迁移不会重复执行

Revision ID: 20260421a001
Revises: 20260324a001
Create Date: 2026-04-21 13:00:00.000000+08:00
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "20260421a001"
down_revision: str | None = "20260324a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES = [
    ("xhs_tasks", "ix_xhs_tasks_user_updated", ["user_id", "updated_at"]),
    ("xhs_tasks", "ix_xhs_tasks_user_status", ["user_id", "status"]),
    ("credit_transactions", "idx_ct_user_type", ["user_id", "type"]),
    ("credit_transactions", "idx_ct_user_created", ["user_id", "created_at"]),
    ("invite_records", "idx_ir_inviter_created", ["inviter_id", "created_at"]),
    ("invite_records", "idx_ir_ip_created", ["ip_address", "created_at"]),
    ("announcements", "ix_announcements_published", ["is_published", "published_at"]),
]


def _existing_index_names(inspector, table: str) -> set[str]:
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, idx_name, cols in INDEXES:
        if table not in existing_tables:
            continue
        existing = _existing_index_names(inspector, table)
        if idx_name in existing:
            continue
        op.create_index(idx_name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, idx_name, _ in reversed(INDEXES):
        if table not in existing_tables:
            continue
        existing = _existing_index_names(inspector, table)
        if idx_name not in existing:
            continue
        op.drop_index(idx_name, table_name=table)
