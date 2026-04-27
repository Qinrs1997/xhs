"""add_bio_to_users

Revision ID: dd5af39a69b3
Revises: 2026031401
Create Date: 2026-03-17 12:08:47.318073+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dd5af39a69b3'
down_revision: Union[str, None] = '2026031401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users 表新增 bio（个人简介）字段
    op.add_column('users', sa.Column('bio', sa.String(length=500), nullable=True, comment='个人简介'))


def downgrade() -> None:
    op.drop_column('users', 'bio')
