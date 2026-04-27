"""PaymentService 单元测试

覆盖场景:
- 创建订单(积分包 / 会员)
- Mock 模式支付完成 → 积分发放 / 会员开通
- 边界:不存在的商品、未知订单类型
- 订单查询、历史列表
- 重复支付完成拒绝
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.membership import CreditPack, MembershipPlan, Order
from app.models.user import User
from app.services.payment_service import PaymentService


@pytest.fixture
def payment_svc(monkeypatch):
    """强制使用 mock 模式"""
    svc = PaymentService()

    class _FakeSettings:
        PAYMENT_MODE = "mock"
        APP_PORT = 8000
        PUBLIC_API_BASE = ""  # 空则 mock 支付 URL 回落到 127.0.0.1:APP_PORT
        ALIPAY_APP_ID = ""
        ALIPAY_SANDBOX = True
        ALIPAY_NOTIFY_URL = ""
        ALIPAY_PRIVATE_KEY = ""
        ALIPAY_PUBLIC_KEY = ""
        ALIPAY_RETURN_URL = ""
        FRONTEND_URL = "http://localhost:5173"

    # payment_service 已拆包，settings 真实使用点在 `.service` 子模块
    monkeypatch.setattr("app.services.payment_service.service.settings", _FakeSettings)
    return svc


@pytest_asyncio.fixture
async def user(db_session: AsyncSession) -> User:
    u = User(
        username="payer",
        email="payer@test.com",
        hashed_password="x",
        credits=100,
        total_credits_used=0,
        vip_level="free",
        is_active=True,
    )
    db_session.add(u)
    await db_session.flush()
    return u


@pytest_asyncio.fixture
async def credit_pack(db_session: AsyncSession) -> CreditPack:
    pack = CreditPack(
        name="小礼包",
        credits=100,
        bonus_credits=10,
        price=990,
        is_active=True,
        sort_order=1,
    )
    db_session.add(pack)
    await db_session.flush()
    return pack


@pytest_asyncio.fixture
async def inactive_pack(db_session: AsyncSession) -> CreditPack:
    pack = CreditPack(
        name="下架包",
        credits=50,
        bonus_credits=0,
        price=490,
        is_active=False,
        sort_order=99,
    )
    db_session.add(pack)
    await db_session.flush()
    return pack


@pytest_asyncio.fixture
async def plus_plan(db_session: AsyncSession) -> MembershipPlan:
    plan = MembershipPlan(
        name="plus",
        display_name="进阶版",
        level=1,
        price_monthly=1990,
        price_yearly=19900,
        monthly_credits=500,
        features=["feature_a"],
        max_concurrency=3,
        available_models=["gpt-4o-mini"],
        is_active=True,
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


class TestCreatePayment:
    """创建支付订单"""

    async def test_create_credit_pack_order(self, payment_svc, db_session, user, credit_pack):
        result = await payment_svc.create_payment(
            db_session,
            user_id=user.id,
            order_type="credit_pack",
            item_id=credit_pack.id,
        )
        assert result["order_no"].startswith("CP")
        assert result["amount"] == credit_pack.price
        assert result["mode"] == "mock"
        assert result["payment_url"].startswith("http")

        order = await db_session.scalar(select(Order).where(Order.order_no == result["order_no"]))
        assert order is not None
        assert order.status == "pending"
        assert order.type == "credit_pack"
        assert order.credits_granted == credit_pack.credits + credit_pack.bonus_credits

    async def test_create_membership_monthly(self, payment_svc, db_session, user, plus_plan):
        result = await payment_svc.create_payment(
            db_session,
            user_id=user.id,
            order_type="membership",
            item_id=plus_plan.id,
            period="monthly",
        )
        assert result["order_no"].startswith("MB")
        assert result["amount"] == plus_plan.price_monthly

    async def test_create_membership_yearly(self, payment_svc, db_session, user, plus_plan):
        result = await payment_svc.create_payment(
            db_session,
            user_id=user.id,
            order_type="membership",
            item_id=plus_plan.id,
            period="yearly",
        )
        assert result["amount"] == plus_plan.price_yearly

    async def test_create_with_missing_pack_raises(self, payment_svc, db_session, user):
        with pytest.raises(NotFoundError):
            await payment_svc.create_payment(
                db_session, user_id=user.id, order_type="credit_pack", item_id=99999
            )

    async def test_create_with_inactive_pack_raises(
        self, payment_svc, db_session, user, inactive_pack
    ):
        with pytest.raises(NotFoundError):
            await payment_svc.create_payment(
                db_session,
                user_id=user.id,
                order_type="credit_pack",
                item_id=inactive_pack.id,
            )

    async def test_unknown_order_type_raises(self, payment_svc, db_session, user):
        from app.core.exceptions import BadRequestError
        with pytest.raises(BadRequestError):
            await payment_svc.create_payment(
                db_session, user_id=user.id, order_type="invalid_type", item_id=1
            )


class TestMockComplete:
    """Mock 模式支付完成"""

    async def test_complete_credit_pack_grants_credits(
        self, payment_svc, db_session, user, credit_pack
    ):
        created = await payment_svc.create_payment(
            db_session, user_id=user.id, order_type="credit_pack", item_id=credit_pack.id
        )
        await db_session.refresh(user)
        initial = user.credits

        result = await payment_svc.mock_complete_payment(db_session, created["order_no"])
        assert result["status"] == "paid"

        await db_session.refresh(user)
        expected = credit_pack.credits + credit_pack.bonus_credits
        assert user.credits == initial + expected

        order = await db_session.scalar(
            select(Order).where(Order.order_no == created["order_no"])
        )
        assert order.status == "paid"
        assert order.paid_at is not None

    async def test_complete_membership_sets_vip(
        self, payment_svc, db_session, user, plus_plan
    ):
        created = await payment_svc.create_payment(
            db_session,
            user_id=user.id,
            order_type="membership",
            item_id=plus_plan.id,
            period="monthly",
        )
        result = await payment_svc.mock_complete_payment(db_session, created["order_no"])
        assert result["status"] == "paid"

        await db_session.refresh(user)
        assert user.vip_level == "plus"
        assert user.vip_expire_at is not None
        assert user.credits >= plus_plan.monthly_credits

    async def test_complete_unknown_order_raises(self, payment_svc, db_session):
        with pytest.raises(NotFoundError):
            await payment_svc.mock_complete_payment(db_session, "CPNONEXISTENT")

    async def test_complete_already_paid_raises(
        self, payment_svc, db_session, user, credit_pack
    ):
        created = await payment_svc.create_payment(
            db_session, user_id=user.id, order_type="credit_pack", item_id=credit_pack.id
        )
        await payment_svc.mock_complete_payment(db_session, created["order_no"])

        with pytest.raises(ConflictError):
            await payment_svc.mock_complete_payment(db_session, created["order_no"])


class TestOrderStatus:
    """订单状态查询"""

    async def test_get_status_for_own_order(
        self, payment_svc, db_session, user, credit_pack
    ):
        created = await payment_svc.create_payment(
            db_session, user_id=user.id, order_type="credit_pack", item_id=credit_pack.id
        )
        data = await payment_svc.get_order_status(
            db_session, created["order_no"], user.id
        )
        assert data["order_no"] == created["order_no"]
        assert data["status"] == "pending"

    async def test_get_status_unknown_order_raises(self, payment_svc, db_session, user):
        with pytest.raises(NotFoundError):
            await payment_svc.get_order_status(db_session, "CPNONEXISTENT", user.id)

    async def test_other_user_cannot_query(
        self, payment_svc, db_session, user, credit_pack
    ):
        created = await payment_svc.create_payment(
            db_session, user_id=user.id, order_type="credit_pack", item_id=credit_pack.id
        )
        with pytest.raises(NotFoundError):
            await payment_svc.get_order_status(db_session, created["order_no"], 99999)
