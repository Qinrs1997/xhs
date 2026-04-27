"""add auto_renew to users

Revision ID: 20260324a001
Revises: 20260318a001
Create Date: 2026-03-24 14:34:00.000000+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '20260324a001'
down_revision: Union[str, None] = '20260318a001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # 幂等检查：列是否已存在
    columns = [c["name"] for c in inspector.get_columns("users")]
    if "auto_renew" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "auto_renew",
                sa.Boolean(),
                nullable=False,
                server_default="1",
                comment="是否自动续费",
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "auto_renew")
