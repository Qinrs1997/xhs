"""积分与会员相关的请求/响应模型"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


# ==================== 积分相关 ====================

class CreditBalanceResponse(BaseModel):
    """积分余额响应"""
    credits: int = Field(..., description="当前可用积分")
    vip_level: str = Field(..., description="会员等级")
    vip_display_name: str = Field("免费版", description="会员显示名")
    vip_expire_at: Optional[datetime] = Field(None, description="会员到期时间")
    total_credits_used: int = Field(0, description="累计消耗积分")
    invite_code: Optional[str] = Field(None, description="邀请码")
    checked_in_today: bool = Field(False, description="今天是否已签到")


class CreditTransactionResponse(BaseModel):
    """积分流水记录"""
    id: int
    amount: int = Field(..., description="变动数量")
    balance_after: int = Field(..., description="变动后余额")
    type: str = Field(..., description="类型")
    source: str = Field(..., description="来源")
    reference_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreditTransactionListResponse(BaseModel):
    """积分流水列表"""
    items: List[CreditTransactionResponse]
    total: int
    page: int
    page_size: int


# ==================== 签到 ====================

class CheckinStatusResponse(BaseModel):
    """签到状态"""
    checked_in_today: bool = Field(..., description="今天是否已签到")
    streak_days: int = Field(0, description="连续签到天数")
    next_streak_bonus: int = Field(0, description="距离下次连续奖励还需天数")
    today_credits: int = Field(0, description="今天可获得的积分")
    checkin_dates: List[str] = Field(default=[], description="最近30天签到日期")


class CheckinResponse(BaseModel):
    """签到结果"""
    credits_earned: int = Field(..., description="本次获得积分")
    streak_days: int = Field(..., description="当前连续天数")
    is_streak_bonus: bool = Field(False, description="是否触发连续奖励")
    streak_bonus_credits: int = Field(0, description="连续奖励额外积分")
    new_balance: int = Field(..., description="签到后总积分")


# ==================== 会员方案 ====================

class MembershipPlanResponse(BaseModel):
    """会员方案"""
    id: int
    name: str
    display_name: str
    level: int
    price_monthly: float = Field(..., description="月价（元）")
    price_yearly: float = Field(0, description="年价（元）")
    monthly_credits: int = Field(..., description="月赠积分")
    features: Optional[Union[List[str], Dict[str, Any]]] = None
    max_concurrency: int = 1
    is_active: bool = True

    model_config = {"from_attributes": True}


class MembershipInfoResponse(BaseModel):
    """我的会员信息"""
    vip_level: str
    display_name: str
    expire_at: Optional[datetime] = None
    is_active: bool = Field(..., description="会员是否在有效期内")
    monthly_credits: int = Field(0, description="每月积分额度")
    remaining_credits: int = Field(0, description="当前剩余积分")
    current_plan: Optional[MembershipPlanResponse] = None


class SubscribeRequest(BaseModel):
    """订阅会员请求"""
    plan_id: int = Field(..., gt=0, description="方案ID")
    period: Literal["monthly", "yearly"] = Field("monthly", description="周期: monthly/yearly")
    payment_method: Literal["alipay", "wechat"] = Field("alipay", description="支付方式: alipay/wechat")


# ==================== 积分包 ====================

class CreditPackResponse(BaseModel):
    """积分包"""
    id: int
    name: str
    credits: int
    price: float = Field(..., description="价格（元）")
    bonus_credits: int = Field(0, description="额外赠送")
    total_credits: int = Field(0, description="总获得积分（含赠送）")

    model_config = {"from_attributes": True}


class PurchasePackRequest(BaseModel):
    """购买积分包请求"""
    pack_id: int = Field(..., gt=0, description="积分包ID")
    payment_method: Literal["alipay", "wechat"] = Field("alipay", description="支付方式: alipay/wechat")


# ==================== 邀请 ====================

class InviteStatsResponse(BaseModel):
    """邀请统计"""
    invite_code: str = Field(..., description="我的邀请码")
    total_invited: int = Field(0, description="已邀请人数")
    total_credits_earned: int = Field(0, description="邀请获得的总积分")


# ==================== 管理后台 ====================

class CreditOperationResponse(BaseModel):
    """积分操作结果"""
    amount: int = Field(..., description="变动数量")
    balance_after: int = Field(..., description="变动后余额")
    user_id: Optional[int] = Field(None, description="目标用户ID")
    transaction_id: Optional[int] = Field(None, description="流水ID")
    type: Optional[str] = Field(None, description="流水类型")
    description: Optional[str] = Field(None, description="原因/描述")


class AdminCreditUserResponse(BaseModel):
    """管理员积分用户列表项"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    credits: int
    vip_level: str
    actual_vip_level: str
    vip_expire_at: Optional[datetime] = None
    total_credits_used: int = 0
    created_at: datetime
    last_login_at: Optional[datetime] = None


class AdminCreditUserListResponse(BaseModel):
    """管理员积分用户列表"""
    items: List[AdminCreditUserResponse]
    total: int
    registered_count: int
    page: int
    page_size: int


class AdminCreditBatchAdjustRequest(BaseModel):
    """管理员批量调整积分"""
    user_ids: List[int] = Field(..., min_length=1, max_length=500, description="目标用户ID列表")
    amount: int = Field(..., ge=-1_000_000, le=1_000_000, description="积分数（正=发放,负=扣除）")
    description: str = Field(..., min_length=1, max_length=200, description="调整原因")


class AdminCreditBatchAdjustItem(BaseModel):
    """单个用户积分调整结果"""
    user_id: int
    amount: int
    balance_after: int
    transaction_id: int


class AdminCreditBatchAdjustResponse(BaseModel):
    """批量积分调整结果"""
    updated_count: int
    amount: int
    description: str
    items: List[AdminCreditBatchAdjustItem]


class InviteCodeResponse(BaseModel):
    """邀请码"""
    invite_code: str = Field(..., description="邀请码")


class InviteValidateResponse(BaseModel):
    """邀请码验证结果"""
    valid: bool
    inviter_name: Optional[str] = None


class InviteListResponse(BaseModel):
    """邀请列表"""
    items: List[Dict[str, Any]]
    total: int


class SubscribeResponse(BaseModel):
    """会员订阅结果"""
    order_id: Optional[str] = None
    message: str = ""


class MembershipSetResponse(BaseModel):
    """管理员设置会员结果"""
    user_id: int
    vip_level: str


class PurchaseResponse(BaseModel):
    """积分包购买结果"""
    order_id: Optional[str] = None
    message: str = ""


class AdminCreditStatsResponse(BaseModel):
    """积分消耗统计"""
    total_credits_consumed: int = 0
    total_credits_granted: int = 0
    active_vip_count: int = 0
    total_users: int = 0
    today_used: int = 0
    active_users: int = 0
    type_stats: List[Dict[str, Any]] = Field(default_factory=list)


class AdminCreditGrantRequest(BaseModel):
    """管理员发放/扣除积分"""
    user_id: int = Field(..., gt=0, description="目标用户ID")
    amount: int = Field(..., gt=0, le=1_000_000, description="积分数")
    description: str = Field(..., min_length=1, max_length=200, description="原因")


class AdminSetMembershipRequest(BaseModel):
    """管理员设置会员"""
    user_id: int = Field(..., gt=0, description="目标用户ID")
    vip_level: Literal["free", "plus", "pro", "max"] = Field(..., description="等级: free/plus/pro/max")
    days: int = Field(30, ge=1, le=3660, description="有效天数")
    expire_at: Optional[datetime] = Field(None, description="到期时间（优先级高于 days）")
