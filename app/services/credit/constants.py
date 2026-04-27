"""积分服务常量

集中定义积分相关常量与可热更新配置。
所有子模块共享此处定义，避免循环依赖。
"""
import time

from app.core.config import settings

_CREDIT_COSTS_DEFAULTS = {
    "outline": 5,
    "content": 10,
    "image_standard": 20,
    "image_hd": 40,
    "prompts_batch": 5,
    "prompt_optimize": 3,
    "chat": 2,
    "image_regenerate": 20,
}

_credit_costs_cache: dict | None = None
_credit_costs_cache_time: float = 0
_CREDIT_COSTS_TTL = 60


def get_credit_costs() -> dict:
    """从 settings 读取积分消耗配置，带 60 秒缓存（支持不重启热更新）"""
    global _credit_costs_cache, _credit_costs_cache_time
    now = time.monotonic()
    if _credit_costs_cache is not None and (now - _credit_costs_cache_time) < _CREDIT_COSTS_TTL:
        return _credit_costs_cache
    result = dict(_CREDIT_COSTS_DEFAULTS)
    for key in result:
        config_key = f"CREDITS_COSTS_{key.upper()}"
        val = getattr(settings, config_key, None)
        if val is not None:
            result[key] = int(val)
    _credit_costs_cache = result
    _credit_costs_cache_time = now
    return result


CREDIT_COSTS = get_credit_costs()

CHECKIN_DAILY = getattr(settings, "CREDITS_CHECKIN_DAILY", 5)
CHECKIN_STREAK_BONUS = getattr(settings, "CREDITS_CHECKIN_STREAK_BONUS", 30)
CHECKIN_STREAK_CYCLE = max(getattr(settings, "CREDITS_CHECKIN_STREAK_CYCLE", 7), 1)

REGISTER_BONUS = getattr(settings, "CREDITS_REGISTER_BONUS", 50)

INVITE_REWARD = getattr(settings, "CREDITS_INVITE_REWARD", 100)
INVITEE_REWARD = getattr(settings, "CREDITS_INVITEE_REWARD", 20)
INVITE_DAILY_LIMIT = getattr(settings, "CREDITS_INVITE_DAILY_LIMIT", 10)

VIP_DISPLAY = {
    "free": "免费版",
    "plus": "进阶版",
    "pro": "专业版",
    "max": "旗舰版",
}
