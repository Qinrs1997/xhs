"""安全相关模块：密码加密、JWT token 等

技术栈：
- 密码哈希：bcrypt（直接使用，不再依赖已停维的 passlib）
- JWT：PyJWT（替代已停维的 python-jose）
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError as JWTError, ExpiredSignatureError

from app.core.exceptions import InvalidTokenError, TokenExpiredError

from app.core.config import settings

# bcrypt 加密轮数（从配置读取，可按环境调优）
BCRYPT_ROUNDS = settings.PASSWORD_BCRYPT_ROUNDS


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码 (同步版本)

    Args:
        plain_password: 明文密码
        hashed_password: 哈希密码

    Returns:
        bool: 密码是否匹配
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码 (异步版本)

    将 CPU 密集型的 bcrypt 验证放到线程池执行，避免阻塞事件循环。
    推荐在高并发场景下使用。
    """
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    生成密码哈希 (同步版本)

    Args:
        password: 明文密码

    Returns:
        str: 哈希后的密码
    """
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("utf-8")


async def get_password_hash_async(password: str) -> str:
    """
    生成密码哈希 (异步版本)

    将 CPU 密集型的 bcrypt 哈希放到线程池执行，避免阻塞事件循环。
    """
    return await asyncio.to_thread(get_password_hash, password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建访问令牌 (Access Token)
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access", "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建刷新令牌 (Refresh Token)
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({"exp": expire, "type": "refresh", "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """
    验证 JWT token

    注意：只接受配置中声明的算法，避免 Algorithm Confusion Attack
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]  # 只信任配置中的算法
        )
        return payload
    except ExpiredSignatureError:
        raise TokenExpiredError() from None
    except JWTError:
        raise InvalidTokenError() from None


def create_password_reset_token(user_id: int, email: str) -> str:
    """
    创建密码重置令牌（15分钟有效）

    Args:
        user_id: 用户 ID
        email: 用户邮箱（嵌入 token 中用于二次校验）

    Returns:
        密码重置专用 JWT token
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode = {
        "sub": str(user_id),
        "email": email,
        "type": "password_reset",
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_password_reset_token(token: str) -> dict:
    """
    验证密码重置令牌

    Args:
        token: 密码重置 JWT token

    Returns:
        {"user_id": int, "email": str}

    Raises:
        ValueError: token 无效或已过期
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        if payload.get("type") != "password_reset":
            raise ValueError("无效的重置令牌类型")

        user_id = payload.get("sub")
        email = payload.get("email")
        if not user_id or not email:
            raise ValueError("重置令牌数据不完整")

        return {"user_id": int(user_id), "email": email}
    except JWTError:
        raise ValueError("重置令牌无效或已过期") from None

