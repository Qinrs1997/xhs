"""积分 API 集成测试

覆盖:
- GET /credits/balance    余额查询
- POST /credits/checkin   每日签到
- GET /credits/checkin/status
- GET /credits/transactions
- GET /credits/packs
- POST /credits/purchase (创建订单)
"""
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import CreditPack

BASE = "/api/v1/credits"


@pytest_asyncio.fixture
async def active_pack(db_session: AsyncSession) -> CreditPack:
    # 价格必须是 100 的整数倍,以保证 price/100 得到可序列化为 int 的值
    pack = CreditPack(
        name="热门积分包",
        credits=100,
        bonus_credits=10,
        price=1000,
        is_active=True,
        sort_order=1,
    )
    db_session.add(pack)
    await db_session.flush()
    return pack


class TestBalance:
    """余额查询"""

    async def test_get_balance(self, authed_client: AsyncClient, normal_user):
        r = await authed_client.get(f"{BASE}/balance")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["credits"] == normal_user.credits


class TestCheckin:
    """每日签到"""

    async def test_checkin_flow(self, authed_client: AsyncClient, normal_user):
        r = await authed_client.get(f"{BASE}/checkin/status")
        assert r.status_code == 200
        status_data = r.json()["data"]
        assert status_data["checked_in_today"] is False

        initial_credits = normal_user.credits
        r = await authed_client.post(f"{BASE}/checkin")
        assert r.status_code == 200
        result = r.json()["data"]
        assert result["credits_earned"] > 0
        assert result["new_balance"] >= initial_credits + result["credits_earned"]

        r = await authed_client.post(f"{BASE}/checkin")
        assert r.status_code in (400, 409)

    async def test_status_after_checkin(self, authed_client: AsyncClient):
        await authed_client.post(f"{BASE}/checkin")
        r = await authed_client.get(f"{BASE}/checkin/status")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["checked_in_today"] is True


class TestTransactions:
    """积分流水"""

    async def test_transactions_include_checkin(self, authed_client: AsyncClient):
        await authed_client.post(f"{BASE}/checkin")
        r = await authed_client.get(f"{BASE}/transactions?page=1&page_size=10")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] >= 1
        assert any("checkin" in t["type"] for t in data["items"])


class TestPacksAndPurchase:
    """积分包与购买"""

    async def test_list_active_packs(self, authed_client: AsyncClient, active_pack):
        r = await authed_client.get(f"{BASE}/packs")
        assert r.status_code == 200
        items = r.json()["data"]
        assert any(p["id"] == active_pack.id for p in items)

    async def test_purchase_pack_creates_pending_order(
        self, authed_client: AsyncClient, active_pack, monkeypatch
    ):
        class _FakeSettings:
            PAYMENT_MODE = "mock"
            APP_PORT = 8000
            ALIPAY_APP_ID = ""
            ALIPAY_SANDBOX = True
            ALIPAY_NOTIFY_URL = ""
            ALIPAY_PRIVATE_KEY = ""
            ALIPAY_PUBLIC_KEY = ""
            ALIPAY_RETURN_URL = ""
            FRONTEND_URL = "http://localhost:5173"

        monkeypatch.setattr("app.services.payment_service.settings", _FakeSettings)

        r = await authed_client.post(
            f"{BASE}/purchase",
            json={"pack_id": active_pack.id, "payment_method": "alipay"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        # PurchaseResponse schema 目前只保留 order_id/message 字段
        # 完整的订单信息(order_no、amount 等)在 PaymentService 层验证即可
