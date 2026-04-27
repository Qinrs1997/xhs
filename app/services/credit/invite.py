"""邀请奖励模块:邀请码、邀请注册奖励、邀请统计/明细、注册赠送"""
import random
import string
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InternalError, NotFoundError
from app.core.logger import logger
from app.core.timezone import now_utc
from app.models.membership import CreditTransaction, InviteRecord
from app.models.user import User

from .constants import (
    INVITE_DAILY_LIMIT,
    INVITE_REWARD,
    INVITEE_REWARD,
    REGISTER_BONUS,
)


class InviteMixin:
    """邀请码、邀请奖励、邀请统计"""

    async def grant_register_bonus(
        self, db: AsyncSession, user_id: int
    ) -> CreditTransaction:
        """注册赠送积分"""
        return await self.add_credits(
            db, user_id,
            amount=REGISTER_BONUS,
            type="register_bonus",
            description=f"注册赠送 {REGISTER_BONUS} 积分",
        )

    async def ensure_invite_code(
        self, db: AsyncSession, user_id: int
    ) -> str:
        """确保用户有邀请码(没有则生成)"""
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("用户不存在")

        if user.invite_code:
            return user.invite_code

        for _ in range(10):
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            exists = await db.scalar(
                select(User.id).where(User.invite_code == code)
            )
            if not exists:
                user.invite_code = code
                await db.flush()
                return code

        raise InternalError("生成邀请码失败")

    async def process_invite_reward(
        self,
        db: AsyncSession,
        new_user_id: int,
        invite_code: str,
        ip_address: str | None = None,
    ) -> CreditTransaction | None:
        """处理邀请注册奖励(双向奖励 + 邀请记录 + 防刷)"""
        if not invite_code:
            return None

        inviter = await db.scalar(
            select(User).where(User.invite_code == invite_code)
        )
        if not inviter:
            logger.warning("无效的邀请码: {}", invite_code)
            return None

        if inviter.id == new_user_id:
            logger.warning("用户试图自己邀请自己: user_id={}", new_user_id)
            return None

        already_invited = await db.scalar(
            select(InviteRecord.id).where(InviteRecord.invitee_id == new_user_id)
        )
        if already_invited:
            logger.warning("用户已被邀请过: user_id={}", new_user_id)
            return None

        if ip_address:
            today = now_utc().date()
            today_start = datetime.combine(today, datetime.min.time())
            ip_count = await db.scalar(
                select(func.count(InviteRecord.id)).where(
                    InviteRecord.ip_address == ip_address,
                    InviteRecord.created_at >= today_start,
                )
            ) or 0
            if ip_count >= 3:
                logger.warning("IP 邀请防刷触发: ip={}, count={}", ip_address, ip_count)
                return None

        today = now_utc().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_invite_count = await db.scalar(
            select(func.count(InviteRecord.id)).where(
                InviteRecord.inviter_id == inviter.id,
                InviteRecord.created_at >= today_start,
            )
        ) or 0

        new_user = await db.get(User, new_user_id)
        if new_user:
            new_user.invited_by = inviter.id

        inviter_reward_amount = 0
        tx = None
        if today_invite_count < INVITE_DAILY_LIMIT:
            tx = await self.add_credits(
                db, inviter.id,
                amount=INVITE_REWARD,
                type="invite_reward",
                description=f"邀请好友注册奖励 +{INVITE_REWARD}",
                reference_id=str(new_user_id),
            )
            inviter_reward_amount = INVITE_REWARD
        else:
            logger.info("邀请人今日奖励已达上限: inviter={}", inviter.id)

        invitee_reward_amount = INVITEE_REWARD
        await self.add_credits(
            db, new_user_id,
            amount=INVITEE_REWARD,
            type="invite_reward",
            description=f"受邀注册奖励 +{INVITEE_REWARD}",
            reference_id=str(inviter.id),
        )

        record = InviteRecord(
            inviter_id=inviter.id,
            invitee_id=new_user_id,
            invite_code=invite_code,
            inviter_reward=inviter_reward_amount,
            invitee_reward=invitee_reward_amount,
            status="completed",
            ip_address=ip_address,
        )
        db.add(record)

        logger.info(
            "邀请奖励: inviter={}(+{}), invitee={}(+{})",
            inviter.id, inviter_reward_amount,
            new_user_id, invitee_reward_amount,
        )
        return tx

    async def get_invite_stats(
        self, db: AsyncSession, user_id: int
    ) -> dict:
        """邀请统计"""
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("用户不存在")
        invite_code = user.invite_code or ""

        total_invited = await db.scalar(
            select(func.count(User.id)).where(User.invited_by == user_id)
        ) or 0

        total_credits = await db.scalar(
            select(func.sum(CreditTransaction.amount)).where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.type == "invite_reward",
            )
        ) or 0

        return {
            "invite_code": invite_code,
            "total_invited": total_invited,
            "total_credits_earned": total_credits,
        }

    async def get_invite_list(
        self,
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """邀请明细列表(分页)"""
        total = await db.scalar(
            select(func.count(InviteRecord.id)).where(
                InviteRecord.inviter_id == user_id
            )
        ) or 0

        result = await db.execute(
            select(
                InviteRecord.id,
                InviteRecord.invitee_id,
                InviteRecord.invite_code,
                InviteRecord.inviter_reward,
                InviteRecord.invitee_reward,
                InviteRecord.status,
                InviteRecord.created_at,
                User.username.label("invitee_name"),
                User.avatar.label("invitee_avatar"),
            )
            .join(User, User.id == InviteRecord.invitee_id)
            .where(InviteRecord.inviter_id == user_id)
            .order_by(InviteRecord.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [
            {
                "id": r.id,
                "invitee_id": r.invitee_id,
                "invitee_name": r.invitee_name,
                "invitee_avatar": r.invitee_avatar,
                "invite_code": r.invite_code,
                "inviter_reward": r.inviter_reward,
                "invitee_reward": r.invitee_reward,
                "status": r.status,
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in result.fetchall()
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
