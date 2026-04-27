"""API 依赖项 (异步版)

该模块提供统一的异步依赖项。不再支持同步数据库会话注入。
"""
import time
from collections import OrderedDict
from typing import Optional
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import verify_token
from app.core.token_blacklist import token_blacklist
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.context import set_current_user
from app.crud import user as user_crud, role as role_crud
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login-token")


_user_cache: OrderedDict[int, tuple[User, float]] = OrderedDict()
_USER_CACHE_TTL = 15
_USER_CACHE_MAX_SIZE = 500


def _get_cached_user(user_id: int) -> Optional[User]:
    """从缓存获取用户（LRU，过期自动清理）"""
    entry = _user_cache.get(user_id)
    if entry is None:
        return None
    user_obj, expire_at = entry
    if time.monotonic() > expire_at:
        _user_cache.pop(user_id, None)
        return None
    _user_cache.move_to_end(user_id)
    return user_obj


def _set_cached_user(user_id: int, user_obj: User) -> None:
    """缓存用户对象（LRU O(1) 淘汰）"""
    if user_id in _user_cache:
        _user_cache.move_to_end(user_id)
    while len(_user_cache) >= _USER_CACHE_MAX_SIZE:
        _user_cache.popitem(last=False)
    _user_cache[user_id] = (user_obj, time.monotonic() + _USER_CACHE_TTL)


def invalidate_user_cache(user_id: int) -> None:
    """失效用户缓存（用户信息变更时调用）"""
    _user_cache.pop(user_id, None)


async def get_current_user(
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    """
    获取当前登录用户 (异步，带缓存 + 黑名单检查)

    安全增强：
    - Token 黑名单检查（登出后立即失效）
    - 用户级 Token 撤销（密码修改后旧 Token 全部失效）

    性能优化：
    - 对活跃用户使用内存缓存（15秒 TTL，多 worker 各自独立）
    """
    credentials_exception = AuthenticationError("无法验证凭证")

    # 1. 检查 token 是否在黑名单中
    if await token_blacklist.is_blacklisted(token):
        raise AuthenticationError("登录已失效，请重新登录")

    # 2. 验证 token
    payload = verify_token(token)
    user_id: Optional[int] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user_id = int(user_id)

    # 3. 检查用户级 Token 撤销（密码修改后旧 token 全部失效）
    iat = payload.get("iat", 0)
    if iat and await token_blacklist.is_user_revoked(user_id, float(iat)):
        raise AuthenticationError("凭证已失效，请重新登录")

    # 4. 先查缓存
    user_obj = _get_cached_user(user_id)

    if user_obj is None:
        # 缓存未命中，查数据库
        user_obj = await user_crud.get(db, id=user_id)
        if user_obj is None:
            raise credentials_exception
        # 写入缓存
        _set_cached_user(user_id, user_obj)

    # 设置上下文（用于日志记录）
    set_current_user(user_id=user_obj.id, user_name=user_obj.username)

    return user_obj


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    获取当前激活用户 (异步)
    """
    if not user_crud.is_active(current_user):
        raise PermissionDeniedError("用户未激活")
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    获取当前超级用户 (异步)
    """
    if not user_crud.is_superuser(current_user):
        raise PermissionDeniedError("权限不足")
    return current_user


async def get_user_from_token_or_query(
    db: AsyncSession = Depends(get_async_db),
    token: str | None = None,
    authorization: str | None = None,
) -> User:
    """从 Header 或 Query 参数获取用户（用于浏览器直接下载等场景）"""
    jwt_token = None
    if authorization and authorization.startswith("Bearer "):
        jwt_token = authorization[7:]
    elif token:
        jwt_token = token

    if not jwt_token:
        raise AuthenticationError("未提供认证凭证，请在 Header 或 Query 参数中传递 token")

    if await token_blacklist.is_blacklisted(jwt_token):
        raise AuthenticationError("登录已失效，请重新登录")

    payload = verify_token(jwt_token)
    uid = payload.get("sub")
    if uid is None:
        raise AuthenticationError("无法验证凭证")
    uid = int(uid)

    iat = payload.get("iat", 0)
    if iat and await token_blacklist.is_user_revoked(uid, float(iat)):
        raise AuthenticationError("凭证已失效，请重新登录")

    user_obj = _get_cached_user(uid)
    if user_obj is None:
        user_obj = await user_crud.get(db, id=uid)
        if user_obj is None:
            raise AuthenticationError("用户不存在")
        _set_cached_user(uid, user_obj)

    if not user_crud.is_active(user_obj):
        raise PermissionDeniedError("用户未激活")

    set_current_user(user_id=user_obj.id, user_name=user_obj.username)
    return user_obj


def require_roles(required_roles: list[str]):
    """
    角色校验依赖 (异步)
    """
    async def _checker(
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user)
    ) -> User:
        # 超级用户直接放行
        if user_crud.is_superuser(current_user):
            return current_user
        if not required_roles:
            raise PermissionDeniedError("权限不足")
        has_role = await role_crud.user_has_any_role(
            db, user_id=current_user.id, role_names=required_roles
        )
        if not has_role:
            raise PermissionDeniedError("权限不足")
        return current_user

    return _checker
