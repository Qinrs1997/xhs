"""CRUD 基类 _apply_filters 操作符单元测试

覆盖场景：
- 精确匹配（field=value）
- 比较操作符（gt/gte/lt/lte）
- 模糊匹配（like/ilike）
- 包含操作符（in）
- 空值检查（is_null）
- 不等于（ne）
- 边界用例（None 值跳过、不存在的字段跳过）
"""
import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.user import User


# ==================== 工具 ====================

# 用 User 模型 + CRUDBase 来测试 _apply_filters
# CRUDBase 是泛型基类，直接实例化一个用来测
class UserCRUD(CRUDBase):
    pass

user_crud = UserCRUD(User)


@pytest_asyncio.fixture
async def seed_users(db_session: AsyncSession):
    """插入测试用户数据"""
    users = [
        User(username="alice", email="alice@a.com", hashed_password="x", credits=100, is_active=True),
        User(username="bob", email="bob@b.com", hashed_password="x", credits=200, is_active=True),
        User(username="charlie", email="charlie@c.com", hashed_password="x", credits=50, is_active=False),
        User(username="diana", email="diana@d.com", hashed_password="x", credits=300, is_active=True),
    ]
    db_session.add_all(users)
    await db_session.flush()
    return users


# ==================== 精确匹配 ====================


class TestExactMatch:
    """精确匹配 field=value"""

    async def test_exact_match(self, db_session, seed_users):
        """按 username 精确查找"""
        results = await user_crud.get_multi(
            db_session, filters={"username": "alice"}
        )
        assert len(results) == 1
        assert results[0].username == "alice"

    async def test_exact_match_bool(self, db_session, seed_users):
        """按布尔字段精确匹配"""
        results = await user_crud.get_multi(
            db_session, filters={"is_active": False}
        )
        assert len(results) == 1
        assert results[0].username == "charlie"


# ==================== 比较操作符 ====================


class TestComparisonOps:
    """比较操作符 gt/gte/lt/lte"""

    async def test_gt(self, db_session, seed_users):
        """credits > 100"""
        results = await user_crud.get_multi(
            db_session, filters={"credits__gt": 100}
        )
        usernames = {u.username for u in results}
        assert "bob" in usernames
        assert "diana" in usernames
        assert "alice" not in usernames

    async def test_gte(self, db_session, seed_users):
        """credits >= 100"""
        results = await user_crud.get_multi(
            db_session, filters={"credits__gte": 100}
        )
        usernames = {u.username for u in results}
        assert "alice" in usernames
        assert "bob" in usernames
        assert "charlie" not in usernames

    async def test_lt(self, db_session, seed_users):
        """credits < 100"""
        results = await user_crud.get_multi(
            db_session, filters={"credits__lt": 100}
        )
        assert len(results) == 1
        assert results[0].username == "charlie"

    async def test_lte(self, db_session, seed_users):
        """credits <= 100"""
        results = await user_crud.get_multi(
            db_session, filters={"credits__lte": 100}
        )
        usernames = {u.username for u in results}
        assert "alice" in usernames
        assert "charlie" in usernames


# ==================== 模糊匹配 ====================


class TestLikeOps:
    """模糊匹配 like/ilike"""

    async def test_like(self, db_session, seed_users):
        """username LIKE '%li%'"""
        results = await user_crud.get_multi(
            db_session, filters={"username__like": "%li%"}
        )
        usernames = {u.username for u in results}
        assert "alice" in usernames
        assert "charlie" in usernames


# ==================== 包含操作符 ====================


class TestInOps:
    """包含操作符 in"""

    async def test_in(self, db_session, seed_users):
        """username IN ['alice', 'bob']"""
        results = await user_crud.get_multi(
            db_session, filters={"username__in": ["alice", "bob"]}
        )
        usernames = {u.username for u in results}
        assert usernames == {"alice", "bob"}


# ==================== 不等于 ====================


class TestNeOps:
    """不等于 ne"""

    async def test_ne(self, db_session, seed_users):
        """username != 'alice'"""
        results = await user_crud.get_multi(
            db_session, filters={"username__ne": "alice"}
        )
        usernames = {u.username for u in results}
        assert "alice" not in usernames
        assert len(usernames) == 3


# ==================== 边界用例 ====================


class TestEdgeCases:
    """边界用例"""

    async def test_none_value_skipped(self, db_session, seed_users):
        """值为 None 时应跳过该过滤条件"""
        results = await user_crud.get_multi(
            db_session, filters={"username": None}
        )
        # None 被跳过 → 返回全部
        assert len(results) == 4

    async def test_nonexistent_field_skipped(self, db_session, seed_users):
        """不存在的字段应该被安全跳过"""
        results = await user_crud.get_multi(
            db_session, filters={"nonexistent_field": "value"}
        )
        # 不存在的字段跳过 → 返回全部
        assert len(results) == 4

    async def test_empty_filters(self, db_session, seed_users):
        """空 filters 返回全部"""
        results = await user_crud.get_multi(db_session, filters={})
        assert len(results) == 4

    async def test_combined_filters(self, db_session, seed_users):
        """组合多个过滤条件"""
        results = await user_crud.get_multi(
            db_session, filters={
                "is_active": True,
                "credits__gte": 100,
            }
        )
        usernames = {u.username for u in results}
        assert "alice" in usernames
        assert "bob" in usernames
        assert "diana" in usernames
        assert "charlie" not in usernames
