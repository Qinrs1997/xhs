"""认证服务层

封装公共认证逻辑：
- 用户认证（用户名/密码验证）
- Token 生成（access + refresh）
- 登录失败锁定（通过缓存层，多进程安全）
- 权限获取
"""
import time
from datetime import timedelta

from app.core.timezone import now_utc
from typing import Any
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token, create_refresh_token,
)
from app.core.exceptions import AuthenticationError
from app.core.logger import logger
from app.crud import user as user_crud


@dataclass
class LoginResult:
    """登录结果数据类"""
    user: Any
    access_token: str
    refresh_token: str
    expires: str
    roles: list[str]
    permissions: list[str]


_LOGIN_ATTEMPT_PREFIX = "login_attempts:"


class AuthService:
    """认证服务类 - 封装公共登录逻辑"""

    @staticmethod
    async def _check_lockout(username: str) -> None:
        """检查用户是否被锁定（通过缓存层，多进程安全）"""
        max_attempts = settings.MAX_LOGIN_ATTEMPTS
        if max_attempts <= 0:
            return

        from app.core.cache import cache
        record = await cache.get(f"{_LOGIN_ATTEMPT_PREFIX}{username}")
        if not record:
            return

        locked_until = record.get("locked_until", 0)
        if locked_until and time.time() < locked_until:
            remaining = int(locked_until - time.time())
            raise AuthenticationError(
                f"登录失败次数过多，账户已锁定，请 {remaining} 秒后重试"
            )

        if locked_until and time.time() >= locked_until:
            await cache.delete(f"{_LOGIN_ATTEMPT_PREFIX}{username}")

    @staticmethod
    async def _record_failed_attempt(username: str) -> None:
        """记录登录失败（通过缓存层，多进程安全）"""
        max_attempts = settings.MAX_LOGIN_ATTEMPTS
        if max_attempts <= 0:
            return

        from app.core.cache import cache
        cache_key = f"{_LOGIN_ATTEMPT_PREFIX}{username}"
        record = await cache.get(cache_key) or {"count": 0, "locked_until": 0}
        record["count"] += 1

        if record["count"] >= max_attempts:
            record["locked_until"] = time.time() + settings.LOCKOUT_DURATION
            logger.warning(
                "用户 {} 登录失败 {} 次，已锁定 {} 秒",
                username, record["count"], settings.LOCKOUT_DURATION,
            )

        ttl = settings.LOCKOUT_DURATION + 60
        await cache.set(cache_key, record, ttl=ttl)

    @staticmethod
    async def _clear_failed_attempts(username: str) -> None:
        """登录成功后清除失败记录"""
        from app.core.cache import cache
        await cache.delete(f"{_LOGIN_ATTEMPT_PREFIX}{username}")

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        username: str,
        password: str
    ) -> Any:
        """
        验证用户凭证

        Args:
            db: 数据库会话
            username: 用户名
            password: 密码

        Returns:
            验证通过的用户对象

        Raises:
            AuthenticationError: 用户名/密码错误或用户未激活/已锁定
        """
        await AuthService._check_lockout(username)

        user = await user_crud.authenticate(
            db,
            username=username,
            password=password
        )

        if not user:
            await AuthService._record_failed_attempt(username)
            raise AuthenticationError("用户名或密码错误")

        if not user_crud.is_active(user):
            await AuthService._record_failed_attempt(username)
            raise AuthenticationError("用户名或密码错误")

        await AuthService._clear_failed_attempts(username)

        return user

    @staticmethod
    def generate_tokens(user_id: int) -> tuple[str, str, str]:
        """
        生成访问令牌和刷新令牌

        Args:
            user_id: 用户 ID

        Returns:
            (access_token, refresh_token, expires_str)
        """
        access_token_expires = timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        expire_time = now_utc() + access_token_expires

        access_token = create_access_token(
            data={"sub": str(user_id)},
            expires_delta=access_token_expires
        )
        refresh_token = create_refresh_token(
            data={"sub": str(user_id)}
        )

        expires_str = expire_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        return access_token, refresh_token, expires_str

    @staticmethod
    def get_user_permissions(user: Any) -> tuple[list[str], list[str]]:
        """
        获取用户角色和权限

        Args:
            user: 用户对象

        Returns:
            (roles, permissions)
        """
        roles = [role.name for role in user.roles]
        permissions = ["*:*:*"] if user.is_superuser else ["announcement:read"]
        return roles, permissions

    @classmethod
    async def login(
        cls,
        db: AsyncSession,
        username: str,
        password: str,
        client_ip: str = "",
    ) -> LoginResult:
        """
        完整登录流程

        Args:
            db: 数据库会话
            username: 用户名
            password: 密码
            client_ip: 客户端 IP（记录最后登录信息）

        Returns:
            LoginResult 包含所有登录信息
        """
        # 1. 验证用户
        user = await cls.authenticate_user(db, username, password)

        # 2. 记录登录信息
        user.last_login_at = now_utc().replace(tzinfo=None)
        if client_ip:
            user.last_login_ip = client_ip
        await db.commit()

        # 3. 生成令牌
        access_token, refresh_token, expires = cls.generate_tokens(user.id)

        # 4. 获取权限
        roles, permissions = cls.get_user_permissions(user)

        return LoginResult(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires=expires,
            roles=roles,
            permissions=permissions
        )

    @staticmethod
    def build_token_response(result: LoginResult):
        """
        构建 Token 响应对象

        Args:
            result: 登录结果

        Returns:
            Token Schema 对象
        """
        from app.schemas import Token
        return Token(
            access_token=result.access_token,
            token_type="bearer",
            accessToken=result.access_token,
            refreshToken=result.refresh_token,
            expires=result.expires,
            username=result.user.username,
            nickname=result.user.full_name or result.user.username,
            avatar=result.user.avatar,
            roles=result.roles,
            permissions=result.permissions
        )


# 全局认证服务实例
auth_service = AuthService()
