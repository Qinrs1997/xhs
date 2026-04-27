"""签到模块:每日签到、签到状态、连续签到奖励"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.timezone import now_utc
from app.models.membership import CheckinRecord
from app.models.user import User

from .constants import CHECKIN_DAILY, CHECKIN_STREAK_BONUS, CHECKIN_STREAK_CYCLE


class CheckinMixin:
    """签到相关"""

    async def get_checkin_status(
        self, db: AsyncSession, user_id: int
    ) -> dict:
        """获取签到状态"""
        today = now_utc().date()

        today_record = await db.scalar(
            select(CheckinRecord).where(
                CheckinRecord.user_id == user_id,
                CheckinRecord.checkin_date == today,
            )
        )

        streak_days = 0
        if today_record:
            streak_days = today_record.streak_days
        else:
            yesterday = today - timedelta(days=1)
            yesterday_record = await db.scalar(
                select(CheckinRecord).where(
                    CheckinRecord.user_id == user_id,
                    CheckinRecord.checkin_date == yesterday,
                )
            )
            if yesterday_record:
                streak_days = yesterday_record.streak_days

        next_streak = CHECKIN_STREAK_CYCLE - (streak_days % CHECKIN_STREAK_CYCLE)
        if next_streak == CHECKIN_STREAK_CYCLE:
            next_streak = 0 if streak_days > 0 else CHECKIN_STREAK_CYCLE

        today_credits = CHECKIN_DAILY
        is_today_checked = today_record is not None
        if not is_today_checked and (streak_days + 1) % CHECKIN_STREAK_CYCLE == 0:
            today_credits += CHECKIN_STREAK_BONUS

        recent_records = await db.execute(
            select(CheckinRecord.checkin_date)
            .where(
                CheckinRecord.user_id == user_id,
                CheckinRecord.checkin_date >= today - timedelta(days=30),
            )
            .order_by(CheckinRecord.checkin_date.desc())
        )
        checkin_dates = [str(r[0]) for r in recent_records.fetchall()]

        return {
            "checked_in_today": is_today_checked,
            "streak_days": streak_days,
            "next_streak_bonus": next_streak if not is_today_checked else
                CHECKIN_STREAK_CYCLE - (streak_days % CHECKIN_STREAK_CYCLE),
            "today_credits": today_credits if not is_today_checked else 0,
            "checkin_dates": checkin_dates,
        }

    async def checkin(self, db: AsyncSession, user_id: int) -> dict:
        """每日签到"""
        today = now_utc().date()

        exists = await db.scalar(
            select(CheckinRecord.id).where(
                CheckinRecord.user_id == user_id,
                CheckinRecord.checkin_date == today,
            )
        )
        if exists:
            raise ConflictError("今天已经签到过了")

        yesterday = today - timedelta(days=1)
        yesterday_record = await db.scalar(
            select(CheckinRecord).where(
                CheckinRecord.user_id == user_id,
                CheckinRecord.checkin_date == yesterday,
            )
        )
        streak_days = (yesterday_record.streak_days + 1) if yesterday_record else 1

        credits_earned = CHECKIN_DAILY
        is_streak_bonus = streak_days % CHECKIN_STREAK_CYCLE == 0
        streak_bonus_credits = CHECKIN_STREAK_BONUS if is_streak_bonus else 0
        total_earned = credits_earned + streak_bonus_credits

        record = CheckinRecord(
            user_id=user_id,
            checkin_date=today,
            streak_days=streak_days,
            credits_earned=total_earned,
        )
        db.add(record)

        await self.add_credits(
            db, user_id,
            amount=total_earned,
            type="daily_checkin" if not is_streak_bonus else "streak_bonus",
            description=f"每日签到 +{credits_earned}" + (
                f",连续{streak_days}天额外奖励 +{streak_bonus_credits}" if is_streak_bonus else ""
            ),
        )

        await db.commit()

        user = await db.get(User, user_id)
        return {
            "credits_earned": credits_earned,
            "streak_days": streak_days,
            "is_streak_bonus": is_streak_bonus,
            "streak_bonus_credits": streak_bonus_credits,
            "new_balance": user.credits,
        }
