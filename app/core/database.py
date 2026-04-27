"""异步数据库连接模块

提供异步数据库会话管理，使用 SQLAlchemy 2.0 AsyncSession。
同时保留同步会话用于 Alembic 迁移和启动初始化。
"""

from typing import AsyncGenerator, Generator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, AsyncAdaptedQueuePool, NullPool, StaticPool
from sqlalchemy.exc import SQLAlchemyError, OperationalError as SAOperationalError

from app.core.config import settings

from app.core.logger import logger


# ==================== 异步引擎 & 会话（主要使用） ====================

def _get_async_database_url() -> str:
    """构建异步数据库连接字符串（使用 asyncmy，C 扩展高性能驱动）"""
    return (
        f"mysql+asyncmy://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}"
        f"?charset={settings.MYSQL_CHARSET}"
    )


# 连接池类型映射
ASYNC_POOL_CLASSES = {
    "queue": AsyncAdaptedQueuePool,  # 默认，适合大多数场景
    "null": NullPool,                # 无连接池，每次创建新连接（测试用）
    "static": StaticPool,            # 静态池，单线程应用
}

# 创建异步数据库引擎
async_engine: AsyncEngine = create_async_engine(
    _get_async_database_url(),
    poolclass=ASYNC_POOL_CLASSES.get(settings.DB_POOL_CLASS, AsyncAdaptedQueuePool),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,  # 添加获取连接超时
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    echo=settings.DB_ECHO,
    connect_args={
        "connect_timeout": settings.DB_CONNECT_TIMEOUT,  # 添加连接超时
    }
)


# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    异步获取数据库会话（API 依赖注入用）

    ╔════════════════════════════════════════════════════════════╗
    ║  ⚠️ 重要：此函数 **不会自动 commit**                        ║
    ║  写操作需要显式调用 await db.commit()                       ║
    ╚════════════════════════════════════════════════════════════╝

    行为说明：
    - 读操作：直接使用，无需 commit
    - 写操作：必须显式调用 await db.commit()
    - 异常时：自动 rollback
    - 退出时：自动关闭会话

    用法示例:
        # 读操作 - 无需 commit
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_async_db)):
            result = await db.execute(select(Item))
            return result.scalars().all()

        # 写操作 - 必须 commit
        @router.post("/items")
        async def create_item(db: AsyncSession = Depends(get_async_db)):
            item = Item(name="xxx")
            db.add(item)
            await db.commit()  # ← 必须显式提交！
            return item

    与 get_async_db_context() 的区别：
    - get_async_db(): 不自动 commit，用于 API 端点
    - get_async_db_context(): 自动 commit，用于后台任务
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # 不自动 commit，让调用方决定
            # CRUD 操作中的 flush() 会将更改写入数据库
            # 正常退出时会话会自动关闭
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error("数据库操作异常: {}", e)
            raise


@asynccontextmanager
async def get_async_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    异步数据库会话上下文管理器（后台任务/脚本用）

    ╔════════════════════════════════════════════════════════════╗
    ║  ✅ 此函数 **会自动 commit**                                ║
    ║  适用于后台任务、定时任务、启动脚本等场景                     ║
    ╚════════════════════════════════════════════════════════════╝

    行为说明：
    - 正常退出：自动 commit
    - 异常时：自动 rollback
    - 退出时：自动关闭会话

    用法示例:
        # 后台任务中使用
        async with get_async_db_context() as db:
            user = User(name="xxx")
            db.add(user)
            # 退出时自动 commit，无需显式调用

    与 get_async_db() 的区别：
    - get_async_db(): 不自动 commit，用于 API 端点
    - get_async_db_context(): 自动 commit，用于后台任务
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error("数据库操作异常: {}", e)
            raise



# ==================== 内部同步引擎 & 会话 (仅限 Alembic 和启动初始化) ====================
# 使用懒加载，避免异步项目中不必要的同步连接池开销

# 同步连接池类型映射
SYNC_POOL_CLASSES = {
    "queue": QueuePool,      # 默认
    "null": NullPool,        # 无连接池
    "static": StaticPool,    # 静态池
}

# 懒加载缓存
_sync_engine = None
_SessionLocal = None


def _get_sync_engine():
    """获取同步引擎（懒加载，仅在需要时创建）"""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.DATABASE_URL,
            poolclass=SYNC_POOL_CLASSES.get(settings.DB_POOL_CLASS, QueuePool),
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=settings.DB_POOL_PRE_PING,
            echo=settings.DB_ECHO,
            connect_args={
                "connect_timeout": settings.DB_CONNECT_TIMEOUT,
            }
        )
    return _sync_engine


def _get_sync_session_factory():
    """获取同步会话工厂（懒加载）"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_get_sync_engine(),
            expire_on_commit=False
        )
    return _SessionLocal

# 注意：Base 类定义在 app/models/base.py 中，不要在此重复定义


def _get_sync_db() -> Generator[Session, None, None]:
    """
    内部同步获取数据库会话

    ⚠️ 仅限：
    - Alembic 数据库迁移
    - 应用启动时的种子数据初始化（极少数情况）
    """
    SessionLocal = _get_sync_session_factory()
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("数据库操作异常: {}", e)
        raise
    finally:
        db.close()


# ==================== 数据库初始化 & 关闭 ====================

def _create_database_if_not_exists() -> None:
    """当目标库不存在时自动创建（需具备创建权限）"""
    db_name = settings.MYSQL_DATABASE
    server_url = (
        f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/?charset={settings.MYSQL_CHARSET}"
    )
    tmp_engine = create_engine(server_url, echo=settings.DB_ECHO, pool_pre_ping=True)
    try:
        with tmp_engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
        logger.info("Database created successfully: {}", db_name)
    except SAOperationalError as e:
        if hasattr(e.orig, "args") and e.orig.args and e.orig.args[0] == 1044:
            logger.error("Permission denied to create database: {}", e)
        raise
    finally:
        tmp_engine.dispose()

def _auto_migrate() -> None:
    """
    自动执行数据库迁移

    策略:
    - 首次运行(无 alembic_version 表):
      用 metadata.create_all 一次性建全部表,然后 alembic stamp head 标记当前版本
    - 非首次运行(已有 alembic_version 表):
      执行 alembic upgrade head 执行增量迁移
    - `settings.AUTO_MIGRATE=False` 时跳过所有建表/迁移动作,仅做 schema 缺失告警。
      生产推荐 Ops 在灰度前独立执行 `alembic upgrade head`,避免多 worker 同时迁移。
    """
    from sqlalchemy import inspect

    if not settings.AUTO_MIGRATE:
        logger.info(
            "AUTO_MIGRATE=False,跳过启动期迁移,请确保已在部署流水线中执行 `alembic upgrade head`"
        )
        return

    engine = _get_sync_engine()
    inspector = inspect(engine)

    # 检测 alembic_version 表是否存在（判断是否首次运行）
    existing_tables = inspector.get_table_names()
    has_alembic = "alembic_version" in existing_tables

    if not has_alembic and len(existing_tables) == 0:
        # ===== 全新数据库：一次性建表 + stamp =====
        logger.info("Fresh database detected — creating all tables...")

        from app.models.base import Base
        # 确保所有模型已导入
        import app.models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        logger.info("Created {} tables", len(Base.metadata.tables))

        # 用 alembic stamp head 标记为最新版本（避免后续 upgrade 重复建表）
        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command as alembic_command
            import os

            # 定位 alembic.ini（从项目根目录）
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            alembic_ini = os.path.join(project_root, "alembic.ini")

            if os.path.exists(alembic_ini):
                alembic_cfg = AlembicConfig(alembic_ini)
                alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
                alembic_command.stamp(alembic_cfg, "head")
                logger.info("Alembic stamped at HEAD")
            else:
                logger.warning("alembic.ini not found at {}, skip stamp", alembic_ini)
        except Exception as e:
            logger.warning("Alembic stamp failed (non-critical): {}", e)
    else:
        # ===== 已有数据库：执行增量迁移 =====
        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command as alembic_command
            import os

            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            alembic_ini = os.path.join(project_root, "alembic.ini")

            if os.path.exists(alembic_ini):
                alembic_cfg = AlembicConfig(alembic_ini)
                alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
                alembic_command.upgrade(alembic_cfg, "head")
                logger.info("Alembic upgrade to HEAD completed")
            else:
                logger.warning("alembic.ini not found at {}, skip migration", alembic_ini)
        except Exception as e:
            logger.warning("Alembic migration failed: {}", e)
            # 如果迁移失败但表不完整，尝试 create_all 补建缺失的表
            if not has_alembic:
                logger.info("Falling back to create_all for missing tables...")
                from app.models.base import Base
                import app.models  # noqa: F401
                Base.metadata.create_all(bind=engine)


def init_db() -> None:
    """
    初始化数据库（同步，应用启动时调用）

    完整流程：
    1. 检测数据库连接 → 数据库不存在则自动创建
    2. 检测是否首次运行（无 alembic_version 表）
       - 首次: metadata.create_all 建全部表 + alembic stamp head
       - 非首次: alembic upgrade head（自动执行增量迁移）
    """
    global _sync_engine, _SessionLocal

    # ===== 第 1 步：确保数据库存在 =====
    try:
        with _get_sync_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(
            "Database connection successful: {}:{}/{}",
            settings.MYSQL_HOST, settings.MYSQL_PORT, settings.MYSQL_DATABASE
        )
    except SAOperationalError as e:
        # 错误码 1049 = Unknown database
        if hasattr(e.orig, "args") and e.orig.args and e.orig.args[0] == 1049:
            logger.warning("Database not found, creating: {}", settings.MYSQL_DATABASE)
            _create_database_if_not_exists()
            # 重置懒加载的同步引擎（旧引擎缓存了不存在的库的连接）
            _sync_engine = None
            _SessionLocal = None
            # 重试连接
            with _get_sync_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(
                "Database created and connected: {}:{}/{}",
                settings.MYSQL_HOST, settings.MYSQL_PORT, settings.MYSQL_DATABASE
            )
        else:
            logger.error("Database connection failed: {}", e)
            raise
    except Exception as e:
        logger.error("Database connection failed: {}", e)
        raise

    # ===== 第 2 步：自动同步表结构 =====
    _auto_migrate()


async def init_async_db() -> None:
    """
    异步初始化数据库连接检查
    """
    try:
        async with async_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Async database connection successful")
    except Exception as e:
        logger.error("Async database connection failed: {}", e)
        raise


def close_db() -> None:
    """关闭内部同步数据库连接（如果已经初始化）"""
    global _sync_engine
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None


async def close_async_db() -> None:
    """关闭异步数据库连接"""
    await async_engine.dispose()
    logger.info("Async database connection closed")
