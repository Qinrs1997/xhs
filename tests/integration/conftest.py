"""集成测试共享 fixtures

覆盖:
- 完整的 HTTP 测试客户端(带认证 override)
- 已登录的普通用户/管理员用户 fixture
- 认证依赖的 override 帮助函数
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser, get_current_user
from app.core.database import get_async_db
from app.main import app
from app.models.user import User


async def _create_user(
    db: AsyncSession, username: str, email: str, *,
    is_superuser: bool = False, credits: int = 1000,
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password="fake_hash",
        credits=credits,
        total_credits_used=0,
        vip_level="free",
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def normal_user(db_session: AsyncSession) -> User:
    return await _create_user(db_session, "e2e_user", "e2e_user@test.com")


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await _create_user(
        db_session, "e2e_admin", "e2e_admin@test.com", is_superuser=True
    )


@pytest_asyncio.fixture
async def authed_client(db_session: AsyncSession, normal_user: User):
    """已登录普通用户的 TestClient"""
    async def _db_override():
        yield db_session

    async def _user_override():
        return normal_user

    app.dependency_overrides[get_async_db] = _db_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_current_active_user] = _user_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession, admin_user: User):
    """已登录管理员的 TestClient"""
    async def _db_override():
        yield db_session

    async def _user_override():
        return admin_user

    app.dependency_overrides[get_async_db] = _db_override
    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_current_active_user] = _user_override
    app.dependency_overrides[get_current_superuser] = _user_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
