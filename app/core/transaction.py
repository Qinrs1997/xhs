"""事务管理模块

提供事务装饰器和上下文管理器，简化数据库事务处理。

使用方法：
    # 方式 1：装饰器（自动 commit/rollback）
    @transactional
    async def create_user_with_role(db: AsyncSession, user_data: dict):
        user = await user_crud.create(db, obj_in=user_data, commit=False)
        await role_crud.assign_to_user(db, user_id=user.id, role_id=1)
        return user  # 装饰器会自动 commit

    # 方式 2：上下文管理器
    async with transaction(db) as session:
        user = await user_crud.create(session, obj_in=user_data, commit=False)
        await role_crud.assign_to_user(session, user_id=user.id, role_id=1)
        # 退出上下文时自动 commit

    # 方式 3：依赖注入（推荐用于 API 层）
    @router.post("/users")
    async def create_user(
        user_data: UserCreate,
        db: AsyncSession = Depends(get_transactional_db)
    ):
        # 所有操作在同一个事务中，请求结束自动 commit
        user = await user_crud.create(db, obj_in=user_data, commit=False)
        return user
"""
import functools
from typing import Callable, TypeVar, ParamSpec, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import AsyncSessionLocal
from app.core.logger import logger

P = ParamSpec("P")
T = TypeVar("T")


# ==================== 事务上下文管理器 ====================

@asynccontextmanager
async def transaction(db: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
    """
    事务上下文管理器

    在上下文块内的所有操作都在同一个事务中。
    正常退出时自动 commit，发生异常时自动 rollback。

    Args:
        db: 异步数据库会话

    Yields:
        同一个 db 会话

    Example:
        async with transaction(db) as session:
            await user_crud.create(session, obj_in=data, commit=False)
            await role_crud.assign_to_user(session, user_id=1, role_id=1)
            # 自动 commit
    """
    try:
        yield db
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error("事务回滚: {}", e)
        raise
    except Exception as e:
        await db.rollback()
        logger.error("事务回滚 (非 SQL 错误): {}", e)
        raise


@asynccontextmanager
async def new_transaction() -> AsyncGenerator[AsyncSession, None]:
    """
    创建新的事务会话（独立于请求上下文）

    适用于后台任务、定时任务等需要独立事务的场景。

    Example:
        async with new_transaction() as db:
            await user_crud.create(db, obj_in=data, commit=False)
            # 自动 commit
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error("独立事务回滚: {}", e)
            raise
        except Exception as e:
            await session.rollback()
            logger.error("独立事务回滚 (非 SQL 错误): {}", e)
            raise


# ==================== 事务装饰器 ====================

def transactional(func: Callable[P, T]) -> Callable[P, T]:
    """
    事务装饰器

    自动管理事务的 commit 和 rollback。
    要求被装饰函数的第一个参数是 db: AsyncSession。

    使用示例：
        @transactional
        async def create_order_with_items(db: AsyncSession, order_data: dict):
            order = await order_crud.create(db, obj_in=order_data, commit=False)
            for item in order_data['items']:
                await item_crud.create(db, obj_in=item, commit=False)
            return order  # 装饰器自动 commit

    注意事项：
        - CRUD 操作需要设置 commit=False
        - 发生异常时自动 rollback
        - 适合需要多个操作原子性的场景
    """
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        # 从参数中获取 db session
        db: AsyncSession = None

        # 尝试从 args 获取
        for arg in args:
            if isinstance(arg, AsyncSession):
                db = arg
                break

        # 尝试从 kwargs 获取
        if db is None:
            db = kwargs.get("db")

        if db is None:
            raise ValueError("transactional 装饰器要求函数参数包含 db: AsyncSession")

        try:
            result = await func(*args, **kwargs)
            await db.commit()
            return result
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("@transactional 事务回滚: {}", e)
            raise
        except Exception as e:
            await db.rollback()
            logger.error("@transactional 事务回滚 (非 SQL 错误): {}", e)
            raise

    return wrapper


# ==================== 事务依赖注入 ====================

async def get_transactional_db() -> AsyncGenerator[AsyncSession, None]:
    """
    事务性数据库会话依赖（自动 commit）

    与 get_async_db 的区别：
    - get_async_db: 不自动 commit，需要手动处理
    - get_transactional_db: 请求成功时自动 commit，失败时自动 rollback

    适用于希望整个请求在一个事务中的场景。

    Example:
        @router.post("/orders")
        async def create_order(
            order_data: OrderCreate,
            db: AsyncSession = Depends(get_transactional_db)
        ):
            # 所有操作自动在同一事务中
            order = await order_crud.create(db, obj_in=order_data, commit=False)
            for item in order_data.items:
                await item_crud.create(db, obj_in=item, commit=False)
            return order  # 请求成功时自动 commit
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error("请求事务回滚: {}", e)
            raise
        except Exception as e:
            await session.rollback()
            logger.error("请求事务回滚 (非 SQL 错误): {}", e)
            raise


# ==================== 嵌套事务支持（Savepoint） ====================

@asynccontextmanager
async def savepoint(db: AsyncSession, name: str | None = None) -> AsyncGenerator[None, None]:
    """
    保存点（Savepoint）上下文管理器

    在已有事务内创建保存点，支持部分回滚。

    Args:
        db: 异步数据库会话
        name: 保存点名称（可选）

    Example:
        async with transaction(db) as session:
            await user_crud.create(session, obj_in=user1, commit=False)

            try:
                async with savepoint(session):
                    await user_crud.create(session, obj_in=user2, commit=False)
                    raise ValueError("模拟错误")
            except ValueError:
                pass  # user2 被回滚，user1 保留

            # 继续其他操作
            await user_crud.create(session, obj_in=user3, commit=False)
            # 最终 commit user1 和 user3
    """
    async with db.begin_nested():
        try:
            yield
        except Exception as e:
            logger.warning("保存点回滚: {}", e)
            raise


# 导出
__all__ = [
    "get_transactional_db",
    "new_transaction",
    "savepoint",
    "transaction",
    "transactional",
]
