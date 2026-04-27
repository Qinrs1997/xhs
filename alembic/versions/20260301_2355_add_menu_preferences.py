"""add menu_preferences to users table

Revision ID: 20260301_2355
Revises: 
Create Date: 2026-03-01 23:55:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = '20260301_2355_add_menu_preferences'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加 menu_preferences JSON 字段到 users 表"""
    op.add_column(
        'users',
        sa.Column(
            'menu_preferences',
            sa.JSON(),
            nullable=True,
            comment='菜单偏好设置(JSON)'
        )
    )


def downgrade() -> None:
    """移除 menu_preferences 字段"""
    op.drop_column('users', 'menu_preferences')
