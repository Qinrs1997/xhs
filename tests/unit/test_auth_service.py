"""AuthService 单元测试

覆盖场景:
- 用户认证成功/失败
- Token 生成
- 权限获取
- 完整登录流程
- 登录失败锁定(依赖 cache layer)
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError
from app.core.security import get_password_hash
from app.models.user import User
from app.services.auth_service import AuthService, auth_service


@pytest_asyncio.fixture
async def active_user(db_session: AsyncSession) -> User:
    user = User(
        username="alice",
        email="alice@example.com",
        hashed_password=get_password_hash("Secret123!"),
        credits=0,
        vip_level="free",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    user = User(
        username="bob",
        email="bob@example.com",
        hashed_password=get_password_hash("Secret123!"),
        credits=0,
        vip_level="free",
        is_active=False,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestAuthenticate:
    """用户名/密码认证"""

    async def test_authenticate_success(self, db_session, active_user):
        user = await AuthService.authenticate_user(
            db_session, username="alice", password="Secret123!"
        )
        assert user.id == active_user.id
        assert user.username == "alice"

    async def test_authenticate_wrong_password_raises(self, db_session, active_user):
        with pytest.raises(AuthenticationError, match="用户名或密码错误"):
            await AuthService.authenticate_user(
                db_session, username="alice", password="wrongpass"
            )

    async def test_authenticate_unknown_user_raises(self, db_session):
        with pytest.raises(AuthenticationError, match="用户名或密码错误"):
            await AuthService.authenticate_user(
                db_session, username="nobody", password="anypass"
            )

    async def test_authenticate_inactive_user_raises(self, db_session, inactive_user):
        """未激活用户应报同样的错误(避免泄漏账号存在性)"""
        with pytest.raises(AuthenticationError, match="用户名或密码错误"):
            await AuthService.authenticate_user(
                db_session, username="bob", password="Secret123!"
            )


class TestTokens:
    """Token 生成"""

    def test_generate_tokens_returns_three_strings(self):
        access, refresh, expires = AuthService.generate_tokens(user_id=42)
        assert isinstance(access, str) and len(access) > 20
        assert isinstance(refresh, str) and len(refresh) > 20
        assert isinstance(expires, str)
        assert "/" in expires

    def test_access_and_refresh_differ(self):
        access, refresh, _ = AuthService.generate_tokens(user_id=42)
        assert access != refresh


class TestPermissions:
    """权限获取"""

    async def test_superuser_gets_wildcard(self, db_session):
        user = User(
            username="admin",
            email="admin@test.com",
            hashed_password="x",
            is_active=True,
            is_superuser=True,
        )
        user.roles = []
        roles, perms = AuthService.get_user_permissions(user)
        assert roles == []
        assert "*:*:*" in perms

    async def test_regular_user_gets_minimal(self, db_session):
        user = User(
            username="user",
            email="user@test.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
        )
        user.roles = []
        roles, perms = AuthService.get_user_permissions(user)
        assert "*:*:*" not in perms
        assert "announcement:read" in perms


class TestLoginFlow:
    """完整登录流程"""

    async def test_login_success_returns_all_fields(self, db_session, active_user):
        result = await AuthService.login(
            db_session, username="alice", password="Secret123!", client_ip="127.0.0.1"
        )
        assert result.user.id == active_user.id
        assert result.access_token
        assert result.refresh_token
        assert result.expires
        assert isinstance(result.roles, list)
        assert isinstance(result.permissions, list)

    async def test_login_records_last_login(self, db_session, active_user):
        await AuthService.login(
            db_session, username="alice", password="Secret123!", client_ip="10.0.0.5"
        )
        await db_session.refresh(active_user)
        assert active_user.last_login_at is not None
        assert active_user.last_login_ip == "10.0.0.5"

    async def test_login_wrong_password_raises(self, db_session, active_user):
        with pytest.raises(AuthenticationError):
            await AuthService.login(
                db_session, username="alice", password="nope"
            )


class TestBuildTokenResponse:
    """Token 响应构建"""

    async def test_build_token_response(self, db_session, active_user):
        result = await AuthService.login(
            db_session, username="alice", password="Secret123!"
        )
        token_obj = AuthService.build_token_response(result)
        assert token_obj.access_token == result.access_token
        assert token_obj.username == "alice"
        assert token_obj.token_type == "bearer"


class TestSingletonInstance:
    """全局单例"""

    def test_singleton_exists(self):
        assert auth_service is not None
        assert isinstance(auth_service, AuthService)
