"""Pytest 配置和 Fixtures

提供测试用的数据库会话、HTTP 客户端、和测试工具。
"""
import asyncio
import os

# 必须在导入 app.* 之前设置,避免开发机 .env 里的 REDIS_ENABLED/真实 MYSQL 凭证
# 污染测试上下文;`setdefault` 允许 CI 通过 APP_ENV=test 覆盖
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("MYSQL_PASSWORD", os.environ.get("MYSQL_PASSWORD", "test"))
os.environ.setdefault("SECRET_KEY", os.environ.get("SECRET_KEY", "test-secret-key-" + "a" * 24))
os.environ.setdefault("REDIS_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import get_async_db
from app.models.base import Base
from app.main import app


# ==================== 事件循环 ====================

@pytest.fixture(scope="session")
def event_loop():
    """为整个测试会话使用同一个事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==================== 测试数据库 ====================

# 使用 SQLite 内存数据库进行单元测试（无需 MySQL）
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function")
async def db_session():
    """
    为每个测试函数创建独立的数据库会话

    使用 SQLite 内存数据库，每次测试自动建表和清理。
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ==================== HTTP 测试客户端 ====================

@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    """
    提供测试用的 HTTPX AsyncClient

    自动将数据库依赖替换为测试用的内存数据库。
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_async_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ==================== 测试工具 ====================

@pytest_asyncio.fixture
async def admin_token(client: AsyncClient):
    """
    获取管理员 Token（用于需要认证的 API 测试）

    注意：需要数据库中有 admin 用户，
    这通常由 app 启动时的 ensure_admin 完成。
    如果是纯内存数据库测试，可能需要先创建用户。
    """
    response = await client.post(
        f"{settings.API_V1_PREFIX}/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    if response.status_code == 200:
        data = response.json()
        token = data.get("data", {}).get("access_token") or data.get("access_token")
        return token
    return None


def auth_headers(token: str) -> dict:
    """构造认证请求头"""
    return {"Authorization": f"Bearer {token}"}
