"""add xhs_templates image generation mode fields

新增字段（用于成本/画质双模式生图）:
- image_generation_mode: 生图模式 VARCHAR(16), 枚举 per_page / batch_grid, 默认 per_page
- image_grid_config: batch_grid 专用布局配置 JSON, 可空
- negative_style_prompt: 模板级负向风格约束 TEXT, 可空（配合 P2-A7 硬约束）

说明:
- 老库 create_all 已经建过对应字段时，本迁移通过 inspector 幂等跳过
- 老数据: image_generation_mode='per_page'（和原行为一致）, image_grid_config=NULL,
  negative_style_prompt=NULL
- per_page 为默认模式,保证老模板零行为变化

Revision ID: 20260423a001
Revises: 20260422a001
Create Date: 2026-04-23 11:30:00.000000+08:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260423a001"
down_revision: str | None = "20260422a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE = "xhs_templates"


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    if "image_generation_mode" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "image_generation_mode",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'per_page'"),
                comment=(
                    "生图模式: per_page=每页独立生成(质量最佳); "
                    "batch_grid=一次API出网格图+后端切割(成本降约4x)"
                ),
            ),
        )

    if "image_grid_config" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "image_grid_config",
                sa.JSON(),
                nullable=True,
                comment=(
                    "batch_grid 模式的网格布局配置 JSON, 如 "
                    '{"rows":2,"cols":2,"cell_size":"1024x1024","gap_px":16}'
                ),
            ),
        )

    if "negative_style_prompt" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "negative_style_prompt",
                sa.Text(),
                nullable=True,
                comment=(
                    "模板级负向风格约束,禁止出现的元素列表文本,"
                    "由 /image/stream 和 /xhs/prompts 硬注入到最终 prompt"
                ),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing = {c["name"] for c in inspector.get_columns(TABLE)}

    if "negative_style_prompt" in existing:
        op.drop_column(TABLE, "negative_style_prompt")
    if "image_grid_config" in existing:
        op.drop_column(TABLE, "image_grid_config")
    if "image_generation_mode" in existing:
        op.drop_column(TABLE, "image_generation_mode")
