"""会员与积分相关模型

包含：
- MembershipPlan: 会员方案表
- CreditTransaction: 积分流水表
- CreditPack: 积分包表
- CheckinRecord: 签到记录表
- Order: 订单表
- InviteRecord: 邀请记录表
"""
from datetime import datetime, date
from typing import Optional, Dict, Any
from sqlalchemy import (
    String, Integer, Boolean, DateTime, Date,
    ForeignKey, JSON, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class MembershipPlan(BaseModel):
    """会员方案表"""
    __tablename__ = "membership_plans"
    __table_args__ = {"comment": "会员方案"}

    name: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False,
        comment="方案标识: free/plus/pro/max"
    )
    display_name: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="显示名称: 免费版/进阶版/专业版/旗舰版"
    )
    level: Mapped[int] = mapped_column(
        Integer, default=0, index=True,
        comment="等级排序: 0=free, 1=plus, 2=pro, 3=max"
    )
    price_monthly: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="月价（分为单位, 2900=¥29）"
    )
    price_yearly: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="年价（分为单位）"
    )
    monthly_credits: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="每月赠送积分"
    )
    features: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
        comment="特权列表 JSON"
    )
    max_concurrency: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="最大并发数"
    )
    available_models: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
        comment="可用模型列表"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="是否启用"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="排序"
    )


class CreditTransaction(BaseModel):
    """积分流水表"""
    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index("idx_ct_user_type", "user_id", "type"),
        Index("idx_ct_user_created", "user_id", "created_at"),
        {"comment": "积分变动记录"},
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="用户ID"
    )
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="变动数量（正=获取, 负=消耗）"
    )
    balance_after: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="变动后余额"
    )
    type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True,
        comment="类型: register_bonus/daily_checkin/usage_outline/purchase 等"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="system",
        comment="来源: system/user/admin"
    )
    reference_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="关联ID（订单号/任务ID等）"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True,
        comment="描述"
    )


class CreditPack(BaseModel):
    """积分包表（可购买）"""
    __tablename__ = "credit_packs"
    __table_args__ = {"comment": "积分包"}

    name: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="显示名称"
    )
    credits: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="积分数"
    )
    price: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="价格（分）"
    )
    bonus_credits: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="额外赠送积分"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="是否启用"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="排序"
    )


class CheckinRecord(BaseModel):
    """签到记录表"""
    __tablename__ = "checkin_records"
    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_user_checkin_date"),
        {"comment": "签到记录"},
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="用户ID"
    )
    checkin_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="签到日期"
    )
    streak_days: Mapped[int] = mapped_column(
        Integer, default=1,
        comment="当前连续签到天数"
    )
    credits_earned: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="本次获得积分"
    )


class Order(BaseModel):
    """订单表"""
    __tablename__ = "orders"
    __table_args__ = {"comment": "订单"}

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="用户ID"
    )
    order_no: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
        comment="订单号"
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="类型: membership/credit_pack"
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="关联方案ID"
    )
    amount: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="订单金额（分）"
    )
    credits_granted: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="赠送积分数"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True,
        comment="状态: pending/paid/cancelled/refunded"
    )
    payment_method: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True,
        comment="支付方式: wechat/alipay/stripe"
    )
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True,
        comment="第三方支付ID"
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="支付时间"
    )
    expire_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True,
        comment="会员到期时间"
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
        comment="额外信息"
    )


class InviteRecord(BaseModel):
    """邀请记录表 — 记录每次邀请的详细信息"""
    __tablename__ = "invite_records"
    __table_args__ = (
        UniqueConstraint("invitee_id", name="uq_invitee_id"),
        Index("idx_ir_inviter_created", "inviter_id", "created_at"),
        Index("idx_ir_ip_created", "ip_address", "created_at"),
        {"comment": "邀请记录"},
    )

    inviter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="邀请人用户ID"
    )
    invitee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="被邀请人用户ID"
    )
    invite_code: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="使用的邀请码"
    )
    inviter_reward: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="邀请人获得的积分奖励"
    )
    invitee_reward: Mapped[int] = mapped_column(
        Integer, default=0,
        comment="被邀请人获得的积分奖励"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="completed",
        comment="状态: completed/revoked"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True,
        comment="被邀请人注册IP（防刷用）"
    )
