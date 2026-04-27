"""seed default membership catalog

Revision ID: 20260424a001
Revises: 20260423a001
Create Date: 2026-04-24 13:00:00.000000+08:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260424a001"
down_revision: str | None = "20260423a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


membership_plans = sa.table(
    "membership_plans",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("display_name", sa.String),
    sa.column("level", sa.Integer),
    sa.column("price_monthly", sa.Integer),
    sa.column("price_yearly", sa.Integer),
    sa.column("monthly_credits", sa.Integer),
    sa.column("features", sa.JSON),
    sa.column("max_concurrency", sa.Integer),
    sa.column("available_models", sa.JSON),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)

credit_packs = sa.table(
    "credit_packs",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("credits", sa.Integer),
    sa.column("price", sa.Integer),
    sa.column("bonus_credits", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)


DEFAULT_MEMBERSHIP_PLANS = [
    {
        "id": 1,
        "name": "plus",
        "display_name": "进阶版",
        "level": 1,
        "price_monthly": 2900,
        "price_yearly": 28800,
        "monthly_credits": 1000,
        "features": ["1000 积分/月", "批量生成", "高级模板", "优先支持"],
        "max_concurrency": 2,
        "available_models": [],
        "is_active": True,
        "sort_order": 10,
    },
    {
        "id": 2,
        "name": "pro",
        "display_name": "专业版",
        "level": 2,
        "price_monthly": 7900,
        "price_yearly": 78800,
        "monthly_credits": 5000,
        "features": ["5000 积分/月", "团队协作", "数据分析", "专属客服"],
        "max_concurrency": 5,
        "available_models": [],
        "is_active": True,
        "sort_order": 20,
    },
    {
        "id": 3,
        "name": "max",
        "display_name": "旗舰版",
        "level": 3,
        "price_monthly": 19900,
        "price_yearly": 198800,
        "monthly_credits": 20000,
        "features": ["20000 积分/月", "API 接入", "私有模板", "最高并发"],
        "max_concurrency": 20,
        "available_models": [],
        "is_active": True,
        "sort_order": 30,
    },
    {
        "id": 4,
        "name": "free",
        "display_name": "免费版",
        "level": 0,
        "price_monthly": 0,
        "price_yearly": 0,
        "monthly_credits": 100,
        "features": ["基础生成", "每日签到", "公开模板"],
        "max_concurrency": 1,
        "available_models": [],
        "is_active": True,
        "sort_order": 0,
    },
]

DEFAULT_CREDIT_PACKS = [
    {
        "id": 1,
        "name": "100 积分",
        "credits": 100,
        "price": 900,
        "bonus_credits": 0,
        "is_active": True,
        "sort_order": 10,
    },
    {
        "id": 2,
        "name": "500 积分",
        "credits": 500,
        "price": 3900,
        "bonus_credits": 50,
        "is_active": True,
        "sort_order": 20,
    },
    {
        "id": 3,
        "name": "1000 积分",
        "credits": 1000,
        "price": 6900,
        "bonus_credits": 150,
        "is_active": True,
        "sort_order": 30,
    },
    {
        "id": 4,
        "name": "5000 积分",
        "credits": 5000,
        "price": 29900,
        "bonus_credits": 1000,
        "is_active": True,
        "sort_order": 40,
    },
]


def _is_empty(table_name: str) -> bool:
    conn = op.get_bind()
    count = conn.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
    return int(count or 0) == 0


def upgrade() -> None:
    if _is_empty("membership_plans"):
        op.bulk_insert(membership_plans, DEFAULT_MEMBERSHIP_PLANS)

    if _is_empty("credit_packs"):
        op.bulk_insert(credit_packs, DEFAULT_CREDIT_PACKS)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM membership_plans "
            "WHERE id IN (1, 2, 3, 4) "
            "AND name IN ('plus', 'pro', 'max', 'free')"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM credit_packs "
            "WHERE id IN (1, 2, 3, 4) "
            "AND name IN ('100 积分', '500 积分', '1000 积分', '5000 积分')"
        )
    )
