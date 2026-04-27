"""本地验证 20260421a001 迁移(新增复合索引)是否幂等运行

使用 sqlite 内存库模拟完整流程:
1. Base.metadata.create_all (模拟生产已有全表)
2. 执行 upgrade -> 索引增量落库
3. 再次 upgrade -> 幂等跳过已存在索引
4. downgrade -> 删除索引
5. 再次 downgrade -> 幂等跳过已删除索引

用法:
    python scripts/verify_migration_2026_04.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MYSQL_PASSWORD", "x")
os.environ.setdefault("SECRET_KEY", "x")

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


def _run(engine, cfg, rev_target: str, downgrade: bool = False) -> None:
    script = ScriptDirectory.from_config(cfg)
    with engine.connect() as connection:

        def _do(rev, context):
            if downgrade:
                return script._downgrade_revs(rev_target, rev)
            return script._upgrade_revs(rev_target, rev)

        with EnvironmentContext(
            cfg,
            script,
            fn=_do,
            as_sql=False,
            destination_rev=rev_target,
        ) as env:
            env.configure(connection=connection)
            with env.begin_transaction():
                env.run_migrations()


def _stamp(engine, cfg, revision: str) -> None:
    with engine.begin() as connection:
        ctx = MigrationContext.configure(connection)
        Operations(ctx)
        connection.execute(
            __import__("sqlalchemy").text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            __import__("sqlalchemy").text("DELETE FROM alembic_version")
        )
        connection.execute(
            __import__("sqlalchemy").text(
                f"INSERT INTO alembic_version (version_num) VALUES ('{revision}')"
            )
        )


def main() -> None:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_url = f"sqlite:///{tmp.name}"

    engine = create_engine(db_url)

    from sqlalchemy import text

    import app.models  # noqa: F401
    from app.models.base import Base

    Base.metadata.create_all(engine)
    print(f"[1/7] Base.metadata.create_all -> {len(Base.metadata.tables)} tables")

    target_indexes = [
        ("xhs_tasks", "ix_xhs_tasks_user_updated"),
        ("xhs_tasks", "ix_xhs_tasks_user_status"),
        ("credit_transactions", "idx_ct_user_type"),
        ("credit_transactions", "idx_ct_user_created"),
        ("invite_records", "idx_ir_inviter_created"),
        ("invite_records", "idx_ir_ip_created"),
        ("announcements", "ix_announcements_published"),
    ]
    with engine.begin() as conn:
        for _table, idx_name in target_indexes:
            try:
                conn.execute(text(f"DROP INDEX {idx_name}"))
            except Exception:
                pass
    print("[2/7] 模拟旧库:强制删除所有目标复合索引")

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    _stamp(engine, cfg, "20260324a001")
    print("[3/7] stamped at 20260324a001")

    _run(engine, cfg, "20260421a001")
    inspector = inspect(engine)
    missing = [
        (t, i) for t, i in target_indexes
        if i not in {ix["name"] for ix in inspector.get_indexes(t)}
    ]
    print(f"[4/7] upgrade -> missing: {missing}")
    assert not missing, f"Missing indexes after upgrade: {missing}"

    _run(engine, cfg, "20260421a001")
    print("[5/7] second upgrade (idempotent) -> OK")

    _run(engine, cfg, "20260324a001", downgrade=True)
    inspector = inspect(engine)
    leftover = [
        (t, i) for t, i in target_indexes
        if i in {ix["name"] for ix in inspector.get_indexes(t)}
    ]
    print(f"[6/7] downgrade -> leftover: {leftover}")
    assert not leftover, f"Leftover indexes after downgrade: {leftover}"

    _run(engine, cfg, "20260324a001", downgrade=True)
    print("[7/7] second downgrade (idempotent) -> OK")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
