"""add is_new, is_hot, use_count to xhs_templates

Revision ID: 2026031401
Revises: 20260312_0131_add_xhs_templates_and_task_fields
Create Date: 2026-03-14 01:35:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2026031401"
down_revision = "ae291010123b"  # 20260312_0131_add_xhs_templates_and_task_fields
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加模板热门/新品/使用次数字段"""
    # 先检查列是否已存在，避免重复添加
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c["name"] for c in inspector.get_columns("xhs_templates")]

    if "is_new" not in existing_columns:
        op.add_column(
            "xhs_templates",
            sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否为新模板"),
        )
    if "is_hot" not in existing_columns:
        op.add_column(
            "xhs_templates",
            sa.Column("is_hot", sa.Boolean(), nullable=False, server_default=sa.text("0"), comment="是否为热门模板"),
        )
    if "use_count" not in existing_columns:
        op.add_column(
            "xhs_templates",
            sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0"), comment="使用次数"),
        )


def downgrade() -> None:
    """移除模板热门/新品/使用次数字段"""
    op.drop_column("xhs_templates", "use_count")
    op.drop_column("xhs_templates", "is_hot")
    op.drop_column("xhs_templates", "is_new")
