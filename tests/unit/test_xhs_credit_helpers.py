import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.xhs_helpers import (
    calculate_image_credit_cost,
    calculate_prompt_credit_cost,
    deduct_xhs_credits,
    ensure_xhs_credits,
)
from app.core.exceptions import BadRequestError
from app.models.membership import CreditTransaction
from app.models.user import User


@pytest_asyncio.fixture
async def billing_user(db_session: AsyncSession) -> User:
    user = User(
        username="billing-user",
        email="billing@example.com",
        hashed_password="fake_hashed_pw",
        credits=100,
        vip_level="free",
        total_credits_used=0,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def test_xhs_image_credit_cost_uses_image_api_calls():
    assert calculate_image_credit_cost("per_page", 3) == 60
    assert calculate_image_credit_cost("batch_grid", 8, api_calls=2) == 40
    assert calculate_image_credit_cost("per_page", 2, image_quality="hd") == 80


def test_xhs_prompt_credit_cost_is_per_page():
    assert calculate_prompt_credit_cost(0) == 0
    assert calculate_prompt_credit_cost(4) == 20


async def test_ensure_xhs_credits_rejects_insufficient_balance(
    db_session: AsyncSession,
    billing_user: User,
):
    await ensure_xhs_credits(db_session, billing_user.id, 100)

    with pytest.raises(BadRequestError):
        await ensure_xhs_credits(db_session, billing_user.id, 101)


async def test_deduct_xhs_credits_records_usage_transaction(
    db_session: AsyncSession,
    billing_user: User,
):
    await deduct_xhs_credits(
        db_session,
        billing_user.id,
        20,
        transaction_type="usage_image",
        description="XHS image generation",
        reference_id="task-1",
    )
    await db_session.commit()
    await db_session.refresh(billing_user)

    tx = await db_session.scalar(
        select(CreditTransaction).where(CreditTransaction.user_id == billing_user.id)
    )

    assert billing_user.credits == 80
    assert billing_user.total_credits_used == 20
    assert tx is not None
    assert tx.amount == -20
    assert tx.type == "usage_image"
    assert tx.reference_id == "task-1"
