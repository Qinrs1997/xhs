"""CreditService 门面:组合 5 个 Mixin

通过 Mixin 组合保持与原单文件实现完全一致的 API,调用方无需改动。
"""
from .checkin import CheckinMixin
from .core import CreditCoreMixin
from .invite import InviteMixin
from .stats import StatsMixin
from .vip import VipMixin


class CreditService(
    CreditCoreMixin,
    CheckinMixin,
    InviteMixin,
    VipMixin,
    StatsMixin,
):
    """积分核心服务

    组合多个 Mixin 提供:余额/增减、签到、邀请、会员、统计等功能。
    所有积分变动都通过此服务,保证事务一致性和流水记录。
    """


credit_service = CreditService()
