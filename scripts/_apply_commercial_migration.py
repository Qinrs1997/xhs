"""一次性脚本：修正 alembic_version 并应用模板商业化字段迁移。

背景：DB 的 alembic_version 被前置环境写成了 '20260326a001'，本仓库无此 revision。
步骤：
1. 将 alembic_version 强制改写为当前仓库最新 head（迁移前）'20260421a001'
2. 执行 alembic upgrade head（应用 20260422a001_add_xhs_template_commercial_fields）
3. 打印确认新列已存在
"""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.getcwd())

from sqlalchemy import create_engine, text, inspect

from app.core.config import settings
from alembic.config import Config
from alembic import command

engine = create_engine(settings.DATABASE_URL)

with engine.begin() as conn:
    cur = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    print("current alembic_version:", cur)
    conn.execute(text("UPDATE alembic_version SET version_num='20260421a001'"))
    print("stamped to 20260421a001")

cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

print("Running alembic upgrade head ...")
command.upgrade(cfg, "head")

insp = inspect(engine)
cols = {c["name"] for c in insp.get_columns("xhs_templates")}
target = {"price", "is_pro", "author_id", "tags", "content_prompt_template"}
found = sorted(cols & target)
missing = sorted(target - cols)
print("xhs_templates new columns found :", found)
print("xhs_templates new columns missing:", missing)
