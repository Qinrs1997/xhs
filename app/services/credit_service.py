"""积分服务兼容层(shim)

原实现已拆分到 `app.services.credit/` 子包,此文件仅作向后兼容的 re-export。
新代码请直接使用 `from app.services.credit import ...`,以便 IDE 追踪到具体模块。

注意:本文件保留是为了不破坏现有 import 路径(大量 endpoints / tests 依赖)。
"""
from app.services.credit import (
    CHECKIN_DAILY,
    CHECKIN_STREAK_BONUS,
    CHECKIN_STREAK_CYCLE,
    CREDIT_COSTS,
    INVITE_DAILY_LIMIT,
    INVITE_REWARD,
    INVITEE_REWARD,
    REGISTER_BONUS,
    VIP_DISPLAY,
    CreditService,
    credit_service,
    get_credit_costs,
)

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
