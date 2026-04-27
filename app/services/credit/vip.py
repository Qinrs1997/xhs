"""会员模块:VIP 等级设置、积分包、会员方案"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logger import logger
from app.core.timezone import now_utc
from app.models.membership import CreditPack, CreditTransaction, MembershipPlan
from app.models.user import User

from .constants import VIP_DISPLAY


class VipMixin:
    """VIP 等级设置、积分包/会员方案查询"""

    async def set_vip_level(
        self,
        db: AsyncSession,
        user_id: int,
        vip_level: str,
        days: int = 30,
        *,
        source: str = "system",
        reference_id: str | None = None,
        operator_id: int | None = None,
    ) -> CreditTransaction | None:
        """设置用户 VIP 等级,同时发放月度积分"""
        if vip_level not in VIP_DISPLAY:
            logger.warning(
                "VIP 设置失败: user={}, level={}, days={}, source={}, reference_id={}, operator={}, reason=invalid_level",
                user_id,
                vip_level,
                days,
                source,
                reference_id,
                operator_id,
            )
            raise BadRequestError("会员等级无效")

        user = await db.get(User, user_id)
        if not user:
            logger.warning(
                "VIP 设置失败: user={} 不存在, level={}, days={}, source={}, reference_id={}, operator={}",
                user_id,
                vip_level,
                days,
                source,
                reference_id,
                operator_id,
            )
            raise NotFoundError("用户不存在")

        logger.info(
            "VIP 设置开始: user={}, level={}, days={}, source={}, reference_id={}, operator={}",
            user_id,
            vip_level,
            days,
            source,
            reference_id,
            operator_id,
        )

        user.vip_level = vip_level
        if vip_level == "free":
            user.vip_expire_at = None
        else:
            user.vip_expire_at = now_utc().replace(tzinfo=None) + timedelta(days=days)

        plan = await db.scalar(
            select(MembershipPlan).where(MembershipPlan.name == vip_level)
        )
        grant_tx: CreditTransaction | None = None
        if plan and plan.monthly_credits > 0:
            grant_tx = await self.add_credits(
                db, user_id,
                amount=plan.monthly_credits,
                type="monthly_grant",
                description=f"开通{VIP_DISPLAY.get(vip_level, vip_level)},赠送 {plan.monthly_credits} 积分",
                source=source,
                reference_id=reference_id,
            )

        await db.commit()
        logger.info(
            "VIP 设置成功: user={}, level={}, expire_at={}, grant_amount={}, grant_tx={}, source={}, reference_id={}, operator={}",
            user_id,
            vip_level,
            user.vip_expire_at,
            plan.monthly_credits if plan else 0,
            grant_tx.id if grant_tx else None,
            source,
            reference_id,
            operator_id,
        )
        return grant_tx

    async def get_credit_packs(self, db: AsyncSession) -> list[dict]:
        """获取可购买的积分包列表"""
        result = await db.execute(
            select(CreditPack)
            .where(CreditPack.is_active == True)  # noqa: E712
            .order_by(CreditPack.sort_order)
        )
        packs = result.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "credits": p.credits,
                "price": p.price / 100,
                "price_cents": p.price,
                "bonus_credits": p.bonus_credits,
                "total_credits": p.credits + p.bonus_credits,
            }
            for p in packs
        ]

    async def get_membership_plans(self, db: AsyncSession) -> list[dict]:
        """获取所有会员方案"""
        result = await db.execute(
            select(MembershipPlan)
            .where(MembershipPlan.is_active == True)  # noqa: E712
            .order_by(MembershipPlan.level)
        )
        plans = result.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "level": p.level,
                "price_monthly": p.price_monthly / 100,
                "price_yearly": p.price_yearly / 100,
                "price_monthly_cents": p.price_monthly,
                "price_yearly_cents": p.price_yearly,
                "monthly_credits": p.monthly_credits,
                "features": p.features or [],
                "max_concurrency": p.max_concurrency,
                "available_models": p.available_models or [],
                "is_active": p.is_active,
            }
            for p in plans
        ]
