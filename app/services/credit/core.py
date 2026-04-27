"""积分核心:余额查询、增减、流水、管理员操作、成本查询"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.logger import logger
from app.core.timezone import now_utc
from app.models.membership import CheckinRecord, CreditTransaction
from app.models.user import User

from .constants import CREDIT_COSTS, VIP_DISPLAY


def _build_transaction_filter(type_filter: str | None):
    """Build user-facing transaction filters while keeping exact type fallback."""
    if not type_filter:
        return None

    normalized = type_filter.strip()
    if not normalized:
        return None

    if normalized in {"earn", "income", "grant"}:
        return CreditTransaction.amount > 0
    if normalized in {"usage", "expense", "deduct"}:
        return CreditTransaction.amount < 0
    if normalized == "checkin":
        return CreditTransaction.type.in_(["checkin", "daily_checkin", "streak_bonus"])
    if normalized == "invite":
        return CreditTransaction.type == "invite_reward"
    if normalized == "admin":
        return CreditTransaction.type.in_(["admin_grant", "admin_deduct"])

    return CreditTransaction.type == normalized


class CreditCoreMixin:
    """积分核心操作:查余额、增减、流水、管理员操作"""

    async def get_balance(self, db: AsyncSession, user_id: int) -> dict:
        user = await db.get(User, user_id)
        if not user:
            raise NotFoundError("用户不存在")

        vip_active = user.is_vip_active
        actual_level = user.actual_vip_level

        today = now_utc().date()
        today_checkin = await db.scalar(
            select(CheckinRecord.id).where(
                CheckinRecord.user_id == user_id,
                CheckinRecord.checkin_date == today,
            )
        )

        return {
            "credits": user.credits,
            "vip_level": actual_level,
            "vip_display_name": VIP_DISPLAY.get(actual_level, "免费版"),
            "vip_expire_at": user.vip_expire_at if vip_active else None,
            "total_credits_used": user.total_credits_used,
            "invite_code": user.invite_code,
            "checked_in_today": today_checkin is not None,
        }

    async def check_balance(
        self, db: AsyncSession, user_id: int, cost: int
    ) -> None:
        """检查余额是否足够(不够则抛异常)"""
        user = await db.get(User, user_id)
        if not user:
            logger.warning("积分余额校验失败: user={} 不存在, cost={}", user_id, cost)
            raise NotFoundError("用户不存在")
        if user.credits < cost:
            logger.warning(
                "积分余额不足: user={}, balance={}, required={}",
                user_id,
                user.credits,
                cost,
            )
            raise BadRequestError(
                f"积分不足,当前 {user.credits} 分,本次操作需要 {cost} 分"
            )

    async def deduct(
        self,
        db: AsyncSession,
        user_id: int,
        amount: int,
        type: str,
        description: str = "",
        reference_id: str | None = None,
        source: str = "system",
    ) -> CreditTransaction:
        """扣除积分(原子操作,防并发超扣)"""
        cost = abs(amount)
        if cost <= 0:
            raise BadRequestError("扣除积分数量必须大于 0")

        result = await db.execute(
            update(User)
            .where(User.id == user_id, User.credits >= cost)
            .values(
                credits=User.credits - cost,
                total_credits_used=User.total_credits_used + cost,
            )
        )

        if result.rowcount == 0:
            user = await db.get(User, user_id)
            if not user:
                logger.warning(
                    "积分扣除失败: user={} 不存在, amount={}, type={}, source={}, reference_id={}",
                    user_id,
                    cost,
                    type,
                    source,
                    reference_id,
                )
                raise NotFoundError("用户不存在")
            logger.warning(
                "积分扣除失败: user={}, amount={}, balance={}, type={}, source={}, reference_id={}, reason=insufficient_balance",
                user_id,
                cost,
                user.credits,
                type,
                source,
                reference_id,
            )
            raise BadRequestError(
                f"积分不足,当前 {user.credits} 分,本次操作需要 {cost} 分"
            )

        new_balance = (await db.execute(
            select(User.credits).where(User.id == user_id)
        )).scalar_one()

        tx = CreditTransaction(
            user_id=user_id,
            amount=-cost,
            balance_after=new_balance,
            type=type,
            source=source,
            reference_id=reference_id,
            description=description or f"消耗 {cost} 积分",
        )
        db.add(tx)
        await db.flush()

        logger.info(
            "积分扣除成功: tx={}, user={}, amount=-{}, balance_after={}, type={}, source={}, reference_id={}, description={}",
            tx.id,
            user_id,
            cost,
            new_balance,
            type,
            source,
            reference_id,
            tx.description,
        )
        return tx

    async def add_credits(
        self,
        db: AsyncSession,
        user_id: int,
        amount: int,
        type: str,
        description: str = "",
        reference_id: str | None = None,
        source: str = "system",
    ) -> CreditTransaction:
        """增加积分(原子操作)"""
        credits = abs(amount)
        if credits <= 0:
            raise BadRequestError("增加积分数量必须大于 0")

        result = await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(credits=User.credits + credits)
        )

        if result.rowcount == 0:
            logger.warning(
                "积分充值失败: user={} 不存在, amount={}, type={}, source={}, reference_id={}",
                user_id,
                credits,
                type,
                source,
                reference_id,
            )
            raise NotFoundError("用户不存在")

        new_balance = (await db.execute(
            select(User.credits).where(User.id == user_id)
        )).scalar_one()

        tx = CreditTransaction(
            user_id=user_id,
            amount=credits,
            balance_after=new_balance,
            type=type,
            source=source,
            reference_id=reference_id,
            description=description or f"获得 {credits} 积分",
        )
        db.add(tx)
        await db.flush()

        logger.info(
            "积分充值成功: tx={}, user={}, amount=+{}, balance_after={}, type={}, source={}, reference_id={}, description={}",
            tx.id,
            user_id,
            credits,
            new_balance,
            type,
            source,
            reference_id,
            tx.description,
        )
        return tx

    async def get_transactions(
        self,
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        type_filter: str | None = None,
    ) -> dict:
        """查询积分流水"""
        query = select(CreditTransaction).where(
            CreditTransaction.user_id == user_id
        )
        filter_clause = _build_transaction_filter(type_filter)
        if filter_clause is not None:
            query = query.where(filter_clause)

        count_query = select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == user_id
        )
        if filter_clause is not None:
            count_query = count_query.where(filter_clause)
        total = await db.scalar(count_query) or 0

        query = query.order_by(CreditTransaction.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_admin_credit_users(
        self,
        db: AsyncSession,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """管理员查询会员/注册用户积分列表"""
        filters = []
        if keyword:
            like = f"%{keyword.strip()}%"
            from sqlalchemy import or_

            filters.append(
                or_(
                    User.username.like(like),
                    User.email.like(like),
                    User.full_name.like(like),
                )
            )

        count_query = select(func.count(User.id))
        query = select(User).order_by(User.created_at.desc(), User.id.desc())
        if filters:
            count_query = count_query.where(*filters)
            query = query.where(*filters)

        total = await db.scalar(count_query) or 0
        registered_count = await db.scalar(select(func.count(User.id))) or 0

        result = await db.execute(
            query.offset((page - 1) * page_size).limit(page_size)
        )
        users = result.scalars().all()

        return {
            "items": [
                {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                    "is_active": user.is_active,
                    "credits": user.credits,
                    "vip_level": user.vip_level,
                    "actual_vip_level": user.actual_vip_level,
                    "vip_expire_at": user.vip_expire_at,
                    "total_credits_used": user.total_credits_used,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                }
                for user in users
            ],
            "total": total,
            "registered_count": registered_count,
            "page": page,
            "page_size": page_size,
        }

    async def admin_adjust_many(
        self,
        db: AsyncSession,
        user_ids: list[int],
        amount: int,
        reason: str,
        admin_id: int,
    ) -> list[CreditTransaction]:
        """管理员批量发放/扣除积分,同一请求内保持整体提交"""
        unique_user_ids = list(dict.fromkeys(user_ids))
        reason = reason.strip()

        if not unique_user_ids:
            raise BadRequestError("请选择需要调整积分的用户")
        if amount == 0:
            raise BadRequestError("积分调整数量不能为 0")
        if not reason:
            raise BadRequestError("请填写积分调整原因")

        rows = await db.execute(
            select(User.id, User.credits).where(User.id.in_(unique_user_ids))
        )
        credits_by_user_id = {row.id: row.credits for row in rows}
        missing_user_ids = [
            user_id for user_id in unique_user_ids if user_id not in credits_by_user_id
        ]
        if missing_user_ids:
            missing_preview = ", ".join(str(user_id) for user_id in missing_user_ids[:10])
            raise NotFoundError(f"用户不存在: {missing_preview}")

        if amount < 0:
            cost = abs(amount)
            insufficient = [
                f"{user_id}(余额 {credits_by_user_id[user_id]})"
                for user_id in unique_user_ids
                if credits_by_user_id[user_id] < cost
            ]
            if insufficient:
                logger.warning(
                    "管理员批量积分调整失败: admin={}, amount={}, targets={}, reason={}, insufficient={}",
                    admin_id,
                    amount,
                    unique_user_ids,
                    reason,
                    insufficient[:10],
                )
                raise BadRequestError(
                    "部分用户积分不足: " + ", ".join(insufficient[:10])
                )

        transactions: list[CreditTransaction] = []
        try:
            logger.info(
                "管理员批量积分调整开始: admin={}, amount={}, targets={}, reason={}",
                admin_id,
                amount,
                unique_user_ids,
                reason,
            )
            if amount > 0:
                for user_id in unique_user_ids:
                    transactions.append(
                        await self.add_credits(
                            db,
                            user_id,
                            amount=amount,
                            type="admin_grant",
                            description=f"管理员发放: {reason}",
                            source="admin",
                            reference_id=str(admin_id),
                        )
                    )
            else:
                for user_id in unique_user_ids:
                    transactions.append(
                        await self.deduct(
                            db,
                            user_id,
                            amount=abs(amount),
                            type="admin_deduct",
                            description=f"管理员扣除: {reason}",
                            source="admin",
                            reference_id=str(admin_id),
                        )
                    )

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception(
                "管理员批量积分调整异常: admin={}, amount={}, targets={}, reason={}",
                admin_id,
                amount,
                unique_user_ids,
                reason,
            )
            raise

        logger.info(
            "管理员批量积分调整成功: admin={}, amount={}, updated_count={}, tx_ids={}, reason={}",
            admin_id,
            amount,
            len(transactions),
            [tx.id for tx in transactions[:20]],
            reason,
        )
        return transactions

    async def admin_grant(
        self,
        db: AsyncSession,
        user_id: int,
        amount: int,
        reason: str,
        admin_id: int,
    ) -> CreditTransaction:
        """管理员发放/扣除积分"""
        reason = reason.strip()
        if amount == 0:
            raise BadRequestError("积分调整数量不能为 0")
        if not reason:
            raise BadRequestError("请填写积分调整原因")

        logger.info(
            "管理员积分调整开始: admin={}, target_user={}, amount={}, reason={}",
            admin_id,
            user_id,
            amount,
            reason,
        )
        if amount > 0:
            tx = await self.add_credits(
                db, user_id,
                amount=amount,
                type="admin_grant",
                description=f"管理员发放: {reason}",
                source="admin",
                reference_id=str(admin_id),
            )
        else:
            tx = await self.deduct(
                db, user_id,
                amount=abs(amount),
                type="admin_deduct",
                description=f"管理员扣除: {reason}",
                source="admin",
                reference_id=str(admin_id),
            )
        await db.commit()
        logger.info(
            "管理员积分调整成功: admin={}, target_user={}, amount={}, tx={}, balance_after={}, type={}, reason={}",
            admin_id,
            user_id,
            tx.amount,
            tx.id,
            tx.balance_after,
            tx.type,
            reason,
        )
        return tx

    def get_cost(self, operation: str, quality: str = "standard") -> int:
        """获取操作的积分消耗"""
        if operation == "image" and quality == "hd":
            return CREDIT_COSTS.get("image_hd", 40)
        return CREDIT_COSTS.get(operation, 0)
