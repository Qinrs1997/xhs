"""Alembic 环境配置"""
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 预加载 .env（确保环境变量在 config 初始化前可用）
from dotenv import load_dotenv
load_dotenv()

# 导入配置和模型
from app.core.config import settings
from app.models.base import Base
from app.models import *  # 导入所有模型，确保 Alembic 能发现它们

# Alembic Config 对象
config = context.config

# 设置数据库 URL
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 解释 Python 日志配置文件
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 添加模型的 MetaData 对象，用于自动生成迁移
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式运行迁移
    
    在这种模式下，不需要实际连接到数据库
    只会生成 SQL 脚本
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 比较列类型
        compare_server_default=True,  # 比较默认值
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移
    
    在这种模式下，会实际连接到数据库并执行迁移
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # 比较列类型
            compare_server_default=True,  # 比较默认值
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

