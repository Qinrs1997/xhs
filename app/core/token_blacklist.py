"""Token 黑名单模块

提供 JWT Token 登出/失效机制。

后端选择（自动）：
- Redis 可用时：通过 cache 模块写入 Redis，支持跨进程/重启持久化
- Redis 不可用时：降级到内存存储（单机模式，进程重启后失效）

使用方法：
    from app.core.token_blacklist import token_blacklist

    # 将 token 加入黑名单（登出时）
    await token_blacklist.add(token, payload)

    # 检查 token 是否在黑名单中
    is_blocked = await token_blacklist.is_blacklisted(token)

    # 使某用户所有 token 失效（修改密码时）
    await token_blacklist.revoke_user(user_id)
"""
import hashlib
import time

from app.core.config import settings
from app.core.logger import logger


# Redis key 前缀
_TOKEN_BL_PREFIX = "token_bl:"
_USER_REVOKE_PREFIX = "user_revoke:"


class TokenBlacklist:
    """Token 黑名单管理器

    使用 token 的 SHA256 摘要作为 key（节省内存，防止 token 泄露）。
    利用 JWT 自身的 exp 时间自动清理过期条目。

    后端策略：
    - Redis 开启时通过 cache 模块存储，跨进程 / 重启不丢失
    - 否则降级到本地 dict（内存模式）
    """

    def __init__(self):
        # --------- 内存 fallback ---------
        # token_hash → expire_timestamp
        self._blacklist: dict[str, float] = {}
        # user_id → revoke_timestamp（该时间之前签发的 token 全部失效）
        self._user_revoke_time: dict[int, float] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 每 5 分钟清理过期条目

    # ----- 工具方法 -----

    @staticmethod
    def _hash_token(token: str) -> str:
        """生成 token 的 SHA256 摘要（前 32 字符，足够唯一）"""
        return hashlib.sha256(token.encode()).hexdigest()[:32]

    @property
    def _use_redis(self) -> bool:
        """判断当前是否使用 Redis 后端"""
        return getattr(settings, "REDIS_ENABLED", False)

    def _get_cache(self):
        """延迟导入 cache 实例，避免循环依赖"""
        from app.core.cache import cache
        return cache

    # ----- 公开 API -----

    async def add(self, token: str, payload: dict) -> None:
        """将 token 加入黑名单

        Args:
            token: JWT token 字符串
            payload: 解码后的 JWT payload（用于获取 exp）
        """
        token_hash = self._hash_token(token)
        exp = payload.get("exp", 0)

        now = time.time()
        if isinstance(exp, (int, float)) and exp > 0:
            ttl = max(int(exp - now), 1)
            expire_at = float(exp)
        else:
            # 没有 exp，默认保留 7 天
            ttl = 7 * 86400
            expire_at = now + ttl

        if self._use_redis:
            cache = self._get_cache()
            await cache.set(f"{_TOKEN_BL_PREFIX}{token_hash}", True, ttl=ttl)
        else:
            self._blacklist[token_hash] = expire_at
            await self._maybe_cleanup()

        logger.debug("Token 已加入黑名单: {}...", token_hash[:8])

    async def is_blacklisted(self, token: str) -> bool:
        """检查 token 是否在黑名单中

        Args:
            token: JWT token 字符串

        Returns:
            True 如果 token 已被注销
        """
        token_hash = self._hash_token(token)

        if self._use_redis:
            cache = self._get_cache()
            return await cache.exists(f"{_TOKEN_BL_PREFIX}{token_hash}")
        else:
            exp = self._blacklist.get(token_hash)
            if exp is not None:
                if time.time() > exp:
                    # 已自然过期，从黑名单移除
                    self._blacklist.pop(token_hash, None)
                    return False
                return True
            return False

    async def is_user_revoked(self, user_id: int, issued_at: float) -> bool:
        """检查用户的 token 是否被全局撤销

        Args:
            user_id: 用户 ID
            issued_at: token 的签发时间（JWT iat claim）

        Returns:
            True 如果该 token 签发时间早于用户的撤销时间
        """
        if self._use_redis:
            cache = self._get_cache()
            revoke_time = await cache.get(f"{_USER_REVOKE_PREFIX}{user_id}")
            if revoke_time is None:
                return False
            return issued_at < float(revoke_time)
        else:
            revoke_time = self._user_revoke_time.get(user_id)
            if revoke_time is None:
                return False
            return issued_at < revoke_time

    async def revoke_user(self, user_id: int) -> None:
        """撤销用户的所有 token（密码修改/重置时调用）

        Args:
            user_id: 用户 ID
        """
        now = time.time()

        if self._use_redis:
            cache = self._get_cache()
            # TTL = refresh token 最大有效期，过期后旧 token 自然失效无需再记录
            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
            await cache.set(f"{_USER_REVOKE_PREFIX}{user_id}", now, ttl=ttl)
        else:
            self._user_revoke_time[user_id] = now

        logger.info("用户 {} 的所有 Token 已撤销", user_id)

    # ----- 内部方法（仅内存模式使用） -----

    async def _maybe_cleanup(self) -> None:
        """定期清理过期的黑名单条目（仅内存模式）"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return

        self._last_cleanup = now

        # 清理过期的 token
        expired = [h for h, exp in self._blacklist.items() if now > exp]
        for h in expired:
            del self._blacklist[h]

        # 清理过期的 user revoke（超过 refresh token 有效期的可以清理）
        max_token_lifetime = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
        expired_users = [
            uid for uid, t in self._user_revoke_time.items()
            if now - t > max_token_lifetime
        ]
        for uid in expired_users:
            del self._user_revoke_time[uid]

        if expired or expired_users:
            logger.debug(
                "Token 黑名单清理: 移除 {} 个 token, {} 个用户撤销记录",
                len(expired), len(expired_users),
            )

    def stats(self) -> dict:
        """获取黑名单统计信息"""
        base = {
            "backend": "redis" if self._use_redis else "memory",
        }
        if not self._use_redis:
            base.update({
                "blacklisted_tokens": len(self._blacklist),
                "revoked_users": len(self._user_revoke_time),
            })
        return base


# 全局黑名单实例
token_blacklist = TokenBlacklist()
