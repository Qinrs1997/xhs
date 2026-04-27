"""核心模块单元测试 — 安全、缓存、CRUD"""
import pytest


# ==================== Security 测试 ====================

class TestSecurity:
    """密码哈希和 JWT 测试"""

    def test_password_hash_and_verify(self):
        """密码哈希 + 验证"""
        from app.core.security import get_password_hash, verify_password

        password = "TestPassword123!"
        hashed = get_password_hash(password)

        assert hashed != password
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_password_hash_different_each_time(self):
        """同一密码每次哈希结果不同（bcrypt salt）"""
        from app.core.security import get_password_hash

        password = "TestPassword123!"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        assert hash1 != hash2  # bcrypt 每次生成不同 salt

    def test_create_and_verify_token(self):
        """JWT 生成 + 验证"""
        from app.core.security import create_access_token, verify_token
        from datetime import timedelta

        token = create_access_token(
            data={"sub": "123"},
            expires_delta=timedelta(minutes=30)
        )

        assert token is not None
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "123"

    def test_expired_token(self):
        """过期 Token 验证应抛出 401"""
        from app.core.security import create_access_token, verify_token
        from app.core.exceptions import TokenExpiredError
        from datetime import timedelta

        token = create_access_token(
            data={"sub": "123"},
            expires_delta=timedelta(seconds=-1)  # 已过期
        )

        with pytest.raises(TokenExpiredError) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401

    def test_invalid_token(self):
        """无效 Token 验证应抛出 401"""
        from app.core.security import verify_token
        from app.core.exceptions import InvalidTokenError

        with pytest.raises(InvalidTokenError) as exc_info:
            verify_token("invalid.token.string")
        assert exc_info.value.status_code == 401


# ==================== 缓存测试 ====================

class TestMemoryCache:
    """内存缓存测试"""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """基本 set/get"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100)
        await cache.set("key1", "value1")

        result = await cache.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        """获取不存在的 key 返回 None"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100)
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """删除 key"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100)
        await cache.set("key1", "value1")
        await cache.delete("key1")

        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """TTL 过期（测试分片锁架构: cache 已升级为 16 分片）"""
        import time as time_mod
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100, default_ttl=1)
        await cache.set("key1", "value1", ttl=1)

        # 定位该 key 所在分片，直接修改过期时间模拟过期
        shard_idx = cache._shard_for("key1")
        async with cache._locks[shard_idx]:
            shard = cache._shards[shard_idx]
            if "key1" in shard:
                shard["key1"].expire_at = time_mod.time() - 1

        result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """LRU 淘汰（分片架构: 每个分片独立容量 max_size // 16）"""
        from app.core.cache import MemoryCache

        # max_size=64 → 每分片 4。写 5 个同分片的 key 验证最早的被驱逐
        # 为了让所有 key 落在同一分片,用相同前缀 + 递增数字(依赖 hash 分布)
        cache = MemoryCache(max_size=64)

        # 找 4 个落到同一分片的 key,然后插入第 5 个验证驱逐
        keys_in_shard: dict[int, list[str]] = {}
        for i in range(200):
            key = f"k{i}"
            idx = cache._shard_for(key)
            keys_in_shard.setdefault(idx, []).append(key)
            if any(len(v) >= 5 for v in keys_in_shard.values()):
                break

        same_shard_keys = next(v for v in keys_in_shard.values() if len(v) >= 5)[:5]
        for i, k in enumerate(same_shard_keys):
            await cache.set(k, i)

        # 第一个被驱逐
        assert await cache.get(same_shard_keys[0]) is None
        # 最后一个仍在
        assert await cache.get(same_shard_keys[-1]) == 4

    @pytest.mark.asyncio
    async def test_exists(self):
        """exists 检查"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100)
        await cache.set("key1", "value1")

        assert await cache.exists("key1") is True
        assert await cache.exists("key2") is False

    @pytest.mark.asyncio
    async def test_clear(self):
        """清空缓存"""
        from app.core.cache import MemoryCache

        cache = MemoryCache(max_size=100)
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()

        assert await cache.get("a") is None
        assert await cache.get("b") is None


# ==================== 验证器测试 ====================

class TestValidators:
    """输入验证器测试"""

    def test_password_strength_valid(self):
        """有效密码通过验证"""
        from app.schemas.validators import validators

        result = validators.password_strength(
            "Abc12345",
            min_length=6,
            require_uppercase=True,
            require_lowercase=True,
            require_digit=True,
            require_special=False,
        )
        assert result == "Abc12345"

    def test_password_too_short(self):
        """密码太短应该失败"""
        from app.schemas.validators import validators

        with pytest.raises(ValueError, match="长度至少"):
            validators.password_strength("Ab1", min_length=6)

    def test_password_missing_uppercase(self):
        """缺少大写字母应该失败"""
        from app.schemas.validators import validators

        with pytest.raises(ValueError, match="大写字母"):
            validators.password_strength(
                "abc12345", require_uppercase=True
            )

    def test_sanitize_string(self):
        """字符串清理"""
        from app.schemas.validators import sanitize_string

        assert sanitize_string("  hello  ") == "hello"
        assert sanitize_string("normal") == "normal"

    def test_mask_sensitive_value(self):
        """敏感值脱敏"""
        from app.schemas.validators import mask_sensitive_value

        assert mask_sensitive_value("secret123", visible_chars=4) == "secr*****"
        assert mask_sensitive_value("ab") == "**"

    def test_mask_dict(self):
        """字典敏感字段脱敏"""
        from app.schemas.validators import mask_dict

        data = {"username": "admin", "password": "secret123"}
        result = mask_dict(data)

        assert result["username"] == "admin"
        assert "secret" not in result["password"]  # password 被脱敏


# ==================== 异常测试 ====================

class TestExceptions:
    """自定义异常测试"""

    def test_exception_to_dict(self):
        """异常转字典"""
        from app.core.exceptions import NotFoundError

        err = NotFoundError("用户不存在")
        d = err.to_dict()

        assert d["code"] == 404
        assert d["error_code"] == "NOT_FOUND"
        assert d["message"] == "用户不存在"

    def test_exception_with_detail(self):
        """异常带详情"""
        from app.core.exceptions import BadRequestError

        err = BadRequestError("参数错误", detail={"field": "name"})
        d = err.to_dict()

        assert d["detail"] == {"field": "name"}

    def test_exception_status_codes(self):
        """所有异常的 status_code 正确"""
        from app.core.exceptions import (
            BadRequestError, AuthenticationError,
            PermissionDeniedError, NotFoundError,
            RateLimitError, InternalError,
        )

        assert BadRequestError().status_code == 400
        assert AuthenticationError().status_code == 401
        assert PermissionDeniedError().status_code == 403
        assert NotFoundError().status_code == 404
        assert RateLimitError().status_code == 429
        assert InternalError().status_code == 500


# ==================== 调度器测试 ====================

class TestScheduler:
    """调度器基础功能测试"""

    def test_trigger_types(self):
        """触发器类型枚举"""
        from app.core.scheduler import TriggerType

        assert TriggerType.CRON.value == "cron"
        assert TriggerType.INTERVAL.value == "interval"
        assert TriggerType.DATE.value == "date"

    def test_job_status(self):
        """任务状态枚举"""
        from app.core.scheduler import JobStatus

        assert JobStatus.PENDING.value == "pending"
        assert JobStatus.RUNNING.value == "running"
        assert JobStatus.PAUSED.value == "paused"

    def test_job_info_to_dict(self):
        """JobInfo 转字典"""
        from app.core.scheduler import JobInfo, TriggerType, JobStatus

        job = JobInfo(
            id="test_job",
            name="测试任务",
            func_name="app.core.tasks.sample",
            trigger_type=TriggerType.INTERVAL,
            trigger_args={"minutes": 30},
            status=JobStatus.PENDING,
            description="测试用",
            is_system=True,
        )

        d = job.to_dict()
        assert d["id"] == "test_job"
        assert d["is_system"] is True
        assert d["trigger_type"] == "interval"


# ==================== Token 黑名单测试 ====================

class TestTokenBlacklist:
    """Token 黑名单测试"""

    @pytest.mark.asyncio
    async def test_add_and_check(self):
        """添加 Token 到黑名单后应被识别"""
        import time as time_mod
        from app.core.token_blacklist import token_blacklist

        fake_payload = {"sub": "1", "exp": time_mod.time() + 3600}
        await token_blacklist.add("test_token_123", fake_payload)

        assert await token_blacklist.is_blacklisted("test_token_123") is True
        assert await token_blacklist.is_blacklisted("other_token") is False
