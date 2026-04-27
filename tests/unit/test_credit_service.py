"""积分服务 + 认证服务 单元测试

覆盖场景：
- 签到（连续签到/重复签到/跨天签到）
- 积分增减（余额不足/正常扣除/正常充值）
- 管理员发放/扣除
- 注册赠送
- 邀请奖励（防重复）
"""
import pytest
import pytest_asyncio
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.credit_service import (
    credit_service,
    CHECKIN_DAILY, CHECKIN_STREAK_BONUS, CHECKIN_STREAK_CYCLE,
    REGISTER_BONUS, INVITE_REWARD, INVITEE_REWARD,
)
from app.models.user import User
from app.models.membership import CheckinRecord, MembershipPlan, CreditPack


# ==================== 工具 fixture ====================

@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """创建测试用户"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password="fake_hashed_pw",
        credits=100,
        vip_level="free",
        total_credits_used=0,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """创建管理员用户"""
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password="fake_hashed_pw",
        credits=9999,
        vip_level="free",
        is_superuser=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def inviter_user(db_session: AsyncSession) -> User:
    """创建带邀请码的用户"""
    user = User(
        username="inviter",
        email="inviter@example.com",
        hashed_password="fake_hashed_pw",
        credits=100,
        vip_level="free",
        invite_code="ABCD1234",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ==================== 签到测试 ====================


class TestCheckin:
    """签到功能测试"""

    async def test_checkin_success(self, db_session, test_user):
        """正常签到"""
        result = await credit_service.checkin(db_session, test_user.id)

        assert result["credits_earned"] == CHECKIN_DAILY
        assert result["streak_days"] == 1
        assert result["is_streak_bonus"] is False
        assert result["new_balance"] == 100 + CHECKIN_DAILY

    async def test_checkin_duplicate_raises(self, db_session, test_user):
        """重复签到应报错"""
        await credit_service.checkin(db_session, test_user.id)

        from app.core.exceptions import ConflictError
        with pytest.raises(ConflictError, match="今天已经签到过了"):
            await credit_service.checkin(db_session, test_user.id)

    async def test_checkin_streak_bonus(self, db_session, test_user):
        """连续 7 天签到触发额外奖励"""
        # 模拟前 6 天签到记录
        today = date.today()
        for i in range(6, 0, -1):
            d = today - timedelta(days=i)
            record = CheckinRecord(
                user_id=test_user.id,
                checkin_date=d,
                streak_days=7 - i,
                credits_earned=CHECKIN_DAILY,
            )
            db_session.add(record)
        await db_session.flush()

        # 第 7 天签到 → 触发连续奖励
        result = await credit_service.checkin(db_session, test_user.id)

        assert result["streak_days"] == CHECKIN_STREAK_CYCLE
        assert result["is_streak_bonus"] is True
        assert result["streak_bonus_credits"] == CHECKIN_STREAK_BONUS
        assert result["credits_earned"] == CHECKIN_DAILY

    async def test_checkin_status(self, db_session, test_user):
        """签到状态查询"""
        # 签到前
        status = await credit_service.get_checkin_status(db_session, test_user.id)
        assert status["checked_in_today"] is False
        assert status["streak_days"] == 0

        # 签到后
        await credit_service.checkin(db_session, test_user.id)
        status = await credit_service.get_checkin_status(db_session, test_user.id)
        assert status["checked_in_today"] is True
        assert status["streak_days"] == 1


# ==================== 积分增减测试 ====================


class TestCredits:
    """积分增减测试"""

    async def test_add_credits(self, db_session, test_user):
        """正常充值积分"""
        tx = await credit_service.add_credits(
            db_session, test_user.id,
            amount=50, type="test_add", description="测试充值",
        )
        assert tx.amount == 50
        assert tx.balance_after == 150
        assert test_user.credits == 150

    async def test_deduct_credits(self, db_session, test_user):
        """正常扣除积分"""
        tx = await credit_service.deduct(
            db_session, test_user.id,
            amount=30, type="test_deduct", description="测试扣除",
        )
        assert tx.amount == -30
        assert tx.balance_after == 70
        assert test_user.credits == 70

    async def test_deduct_over_balance_raises(self, db_session, test_user):
        """扣除超过余额时应抛 BadRequestError（G1 原子化修复后的安全行为）

        历史说明: 旧版是 clamp 到 0，但会导致并发下超扣。G1 修复后
        改为"余额不足直接拒绝"，防止积分漏洞。
        """
        from app.core.exceptions import BadRequestError
        with pytest.raises(BadRequestError, match="积分不足"):
            await credit_service.deduct(
                db_session, test_user.id,
                amount=999, type="test_overdraft",
            )
        # 原余额应保持不变（事务回滚）
        await db_session.refresh(test_user)
        assert test_user.credits == 100

    async def test_check_balance_insufficient(self, db_session, test_user):
        """余额不足应抛异常"""
        from app.core.exceptions import BadRequestError
        with pytest.raises(BadRequestError, match="积分不足"):
            await credit_service.check_balance(db_session, test_user.id, cost=999)

    async def test_check_balance_sufficient(self, db_session, test_user):
        """余额充足不抛异常"""
        await credit_service.check_balance(db_session, test_user.id, cost=50)
        # 不抛就算通过

    async def test_register_bonus(self, db_session, test_user):
        """注册赠送积分"""
        tx = await credit_service.grant_register_bonus(db_session, test_user.id)
        assert tx.amount == REGISTER_BONUS
        assert tx.type == "register_bonus"


# ==================== 管理员操作测试 ====================


class TestAdminCredits:
    """管理员积分操作"""

    async def test_admin_grant(self, db_session, test_user, admin_user):
        """管理员发放积分"""
        tx = await credit_service.admin_grant(
            db_session, test_user.id, amount=200, reason="测试发放", admin_id=admin_user.id
        )
        assert tx.amount == 200
        assert tx.type == "admin_grant"

    async def test_admin_deduct(self, db_session, test_user, admin_user):
        """管理员扣除积分"""
        tx = await credit_service.admin_grant(
            db_session, test_user.id, amount=-50, reason="测试扣除", admin_id=admin_user.id
        )
        assert tx.amount == -50
        assert tx.type == "admin_deduct"
        assert tx.source == "admin"
        assert tx.description == "管理员扣除: 测试扣除"

    async def test_admin_adjust_many_grant(self, db_session, test_user, admin_user):
        """管理员批量发放积分"""
        other_user = User(
            username="batchuser",
            email="batch@example.com",
            hashed_password="fake_hashed_pw",
            credits=10,
            vip_level="free",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()

        txs = await credit_service.admin_adjust_many(
            db_session,
            [test_user.id, other_user.id],
            amount=25,
            reason="活动补偿",
            admin_id=admin_user.id,
        )

        assert len(txs) == 2
        assert {tx.type for tx in txs} == {"admin_grant"}
        assert {tx.source for tx in txs} == {"admin"}
        assert all(tx.description == "管理员发放: 活动补偿" for tx in txs)

        await db_session.refresh(test_user)
        await db_session.refresh(other_user)
        assert test_user.credits == 125
        assert other_user.credits == 35

    async def test_admin_adjust_many_deduct_rejects_insufficient(self, db_session, test_user, admin_user):
        """批量扣除时任一用户余额不足则整体拒绝"""
        poor_user = User(
            username="pooruser",
            email="poor@example.com",
            hashed_password="fake_hashed_pw",
            credits=10,
            vip_level="free",
            is_active=True,
        )
        db_session.add(poor_user)
        await db_session.flush()

        from app.core.exceptions import BadRequestError
        with pytest.raises(BadRequestError, match="部分用户积分不足"):
            await credit_service.admin_adjust_many(
                db_session,
                [test_user.id, poor_user.id],
                amount=-50,
                reason="违规扣除",
                admin_id=admin_user.id,
            )

        await db_session.refresh(test_user)
        await db_session.refresh(poor_user)
        assert test_user.credits == 100
        assert poor_user.credits == 10


# ==================== 积分流水查询测试 ====================


class TestTransactions:
    """积分流水查询"""

    async def test_get_transactions(self, db_session, test_user):
        """查询积分流水"""
        # 先产生几笔流水
        await credit_service.add_credits(db_session, test_user.id, 10, "checkin")
        await credit_service.deduct(db_session, test_user.id, 5, "usage")
        await db_session.flush()

        result = await credit_service.get_transactions(db_session, test_user.id)
        assert result["total"] >= 2
        assert len(result["items"]) >= 2

    async def test_get_transactions_with_filter(self, db_session, test_user):
        """按类型过滤流水"""
        await credit_service.add_credits(db_session, test_user.id, 10, "daily_checkin")
        await credit_service.add_credits(db_session, test_user.id, 20, "purchase")
        await credit_service.deduct(db_session, test_user.id, 5, "usage_image")
        await db_session.flush()

        result = await credit_service.get_transactions(
            db_session, test_user.id, type_filter="checkin"
        )
        for item in result["items"]:
            assert item.type in {"checkin", "daily_checkin", "streak_bonus"}

        earn_result = await credit_service.get_transactions(
            db_session, test_user.id, type_filter="earn"
        )
        assert earn_result["items"]
        assert all(item.amount > 0 for item in earn_result["items"])

        usage_result = await credit_service.get_transactions(
            db_session, test_user.id, type_filter="usage"
        )
        assert usage_result["items"]
        assert all(item.amount < 0 for item in usage_result["items"])


# ==================== 邀请奖励测试 ====================


class TestInviteReward:
    """邀请奖励"""

    async def test_invite_reward(self, db_session, test_user, inviter_user):
        """正常邀请奖励（双向）"""
        tx = await credit_service.process_invite_reward(
            db_session, new_user_id=test_user.id, invite_code="ABCD1234"
        )
        assert tx is not None
        assert tx.amount == INVITE_REWARD

        # 被邀请人也应获得奖励
        await db_session.refresh(test_user)
        assert test_user.credits >= 100 + INVITEE_REWARD

    async def test_invite_reward_invalid_code(self, db_session, test_user):
        """无效邀请码不发奖励"""
        tx = await credit_service.process_invite_reward(
            db_session, new_user_id=test_user.id, invite_code="INVALID"
        )
        assert tx is None

    async def test_invite_reward_self_invite(self, db_session, inviter_user):
        """自己邀请自己不发奖励"""
        tx = await credit_service.process_invite_reward(
            db_session, new_user_id=inviter_user.id, invite_code="ABCD1234"
        )
        assert tx is None


# ==================== 查询方法测试 ====================


class TestServiceQueries:
    """Service 层查询方法（T2 新增方法）"""

    async def test_get_credit_packs(self, db_session):
        """获取积分包列表"""
        # 插入测试积分包
        pack = CreditPack(
            name="测试包", credits=100, price=9.9,
            bonus_credits=10, is_active=True, sort_order=1,
        )
        db_session.add(pack)
        await db_session.flush()

        result = await credit_service.get_credit_packs(db_session)
        assert len(result) >= 1
        assert result[0]["name"] == "测试包"
        assert result[0]["total_credits"] == 110

    async def test_get_membership_plans(self, db_session):
        """获取会员方案列表"""
        plan = MembershipPlan(
            name="pro", display_name="专业版", level=2,
            price_monthly=29.9, price_yearly=299,
            monthly_credits=500, is_active=True,
        )
        db_session.add(plan)
        await db_session.flush()

        result = await credit_service.get_membership_plans(db_session)
        assert len(result) >= 1
        assert result[0]["name"] == "pro"
        assert result[0]["monthly_credits"] == 500

    async def test_get_balance(self, db_session, test_user):
        """获取余额详情"""
        result = await credit_service.get_balance(db_session, test_user.id)
        assert result["credits"] == 100
        assert result["vip_level"] == "free"
        assert result["checked_in_today"] is False
