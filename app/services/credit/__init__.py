"""积分服务包

按职责拆分为 5 个模块(core/checkin/invite/vip/stats),通过 Mixin 组合为 CreditService。
对外 API 与原单文件实现完全一致。

使用示例:
    from app.services.credit_service import credit_service, VIP_DISPLAY
    await credit_service.add_credits(db, user_id, 100, "test")
"""
from .constants import (
    CHECKIN_DAILY,
    CHECKIN_STREAK_BONUS,
    CHECKIN_STREAK_CYCLE,
    CREDIT_COSTS,
    INVITE_DAILY_LIMIT,
    INVITE_REWARD,
    INVITEE_REWARD,
    REGISTER_BONUS,
    VIP_DISPLAY,
    get_credit_costs,
)
from .service import CreditService, credit_service

__all__ = [
    "CHECKIN_DAILY",
    "CHECKIN_STREAK_BONUS",
    "CHECKIN_STREAK_CYCLE",
    "CREDIT_COSTS",
    "INVITEE_REWARD",
    "INVITE_DAILY_LIMIT",
    "INVITE_REWARD",
    "REGISTER_BONUS",
    "VIP_DISPLAY",
    "CreditService",
    "credit_service",
    "get_credit_costs",
]
