"""add xhs_templates commercial fields

新增字段（用于模板市场商业化）:
- content_prompt_template: 正文级提示词模板 (Text, 可空)
- price: 使用该模板单次消耗的积分 (Integer, 默认 0)
- is_pro: 是否 VIP 专享 (Boolean, 默认 false)
- author_id: 模板作者 user_id (FK users.id, 可空)
- tags: 标签数组 (JSON, 可空)

说明:
- 老库 create_all 已经建过对应字段时，本迁移通过 inspector 幂等跳过
- 老数据 price=0, is_pro=False, author_id=NULL, tags=NULL (平台官方模板)

Revision ID: 20260422a001
Revises: 20260421a001
Create Date: 2026-04-22 22:00:00.000000+08:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260422a001"
down_revision: str | None = "20260421a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE = "xhs_templates"


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    if "content_prompt_template" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "content_prompt_template",
                sa.Text(),
                nullable=True,
                comment="正文级提示词模板(Jinja)，用 {{ topic }} 插值",
            ),
        )

    if "price" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "price",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
                comment="使用该模板单次消耗的积分（0=免费）",
            ),
        )

    if "is_pro" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "is_pro",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
                comment="是否 VIP 专享",
            ),
        )

    if "author_id" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "author_id",
                sa.Integer(),
                nullable=True,
                comment="模板作者 user_id（官方模板为 NULL）",
            ),
        )
        # FK + 索引
        op.create_index(
            "ix_xhs_templates_author_id", TABLE, ["author_id"], unique=False
        )
        op.create_foreign_key(
            "fk_xhs_templates_author_id_users",
            TABLE,
            "users",
            ["author_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "tags" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "tags",
                sa.JSON(),
                nullable=True,
                comment="标签数组 (JSON)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns(TABLE)}
    fks = {fk["name"] for fk in inspector.get_foreign_keys(TABLE)}
    idxs = {i["name"] for i in inspector.get_indexes(TABLE)}

    if "tags" in existing:
        op.drop_column(TABLE, "tags")
    if "fk_xhs_templates_author_id_users" in fks:
        op.drop_constraint(
            "fk_xhs_templates_author_id_users", TABLE, type_="foreignkey"
        )
    if "ix_xhs_templates_author_id" in idxs:
        op.drop_index("ix_xhs_templates_author_id", table_name=TABLE)
    if "author_id" in existing:
        op.drop_column(TABLE, "author_id")
    if "is_pro" in existing:
        op.drop_column(TABLE, "is_pro")
    if "price" in existing:
        op.drop_column(TABLE, "price")
    if "content_prompt_template" in existing:
        op.drop_column(TABLE, "content_prompt_template")
