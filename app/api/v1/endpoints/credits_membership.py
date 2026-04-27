"""会员相关接口

- GET  /membership/plans       会员方案列表
- GET  /membership/my          我的会员信息
- POST /membership/subscribe   订阅会员
- POST /membership/cancel      取消续费
"""
from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, AuditLevel, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.exceptions import BadRequestError
from app.core.logger import logger
from app.api.deps import get_current_active_user
from app.models.user import User
from app.models.membership import MembershipPlan
from app.schemas.response import Response
from app.schemas.credit import (
    MembershipInfoResponse, MembershipPlanResponse, MembershipSetResponse,
    SubscribeRequest, SubscribeResponse,
)
from app.services.credit_service import credit_service, VIP_DISPLAY

router = APIRouter()


@router.get("/membership/plans", response_model=Response[list[MembershipPlanResponse]],
            summary="会员方案列表")
async def get_membership_plans(
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    data = await credit_service.get_membership_plans(db)
    return Response(code=200, success=True, message="查询成功", data=data)


@router.get("/membership/my", response_model=Response[MembershipInfoResponse],
            summary="我的会员信息")
async def get_my_membership(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    vip_active = current_user.is_vip_active
    actual_level = current_user.actual_vip_level

    plan = await db.scalar(
        select(MembershipPlan).where(MembershipPlan.name == actual_level)
    )

    plan_data = None
    if plan:
        plan_data = {
            "id": plan.id, "name": plan.name, "display_name": plan.display_name,
            "level": plan.level, "price_monthly": plan.price_monthly,
            "price_yearly": plan.price_yearly, "monthly_credits": plan.monthly_credits,
            "features": plan.features, "max_concurrency": plan.max_concurrency,
            "is_active": plan.is_active,
        }
    data = {
        "vip_level": actual_level,
        "display_name": VIP_DISPLAY.get(actual_level, "免费版"),
        "expire_at": current_user.vip_expire_at if vip_active else None,
        "is_active": vip_active or actual_level == "free",
        "monthly_credits": plan.monthly_credits if plan else 0,
        "remaining_credits": current_user.credits,
        "current_plan": plan_data,
    }
    return Response(code=200, success=True, message="查询成功", data=data)


@router.post("/membership/subscribe", response_model=Response[SubscribeResponse],
             summary="订阅会员")
async def subscribe_membership(
    request: SubscribeRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.PAYMENT,
        description="用户订阅会员",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    from app.services.payment_service import payment_service
    try:
        logger.info(
            "会员订阅下单开始: user={}, plan_id={}, period={}, payment_method={}",
            current_user.id,
            request.plan_id,
            request.period,
            request.payment_method,
        )
        data = await payment_service.create_payment(
            db, current_user.id,
            order_type="membership",
            item_id=request.plan_id,
            period=request.period,
            payment_method=request.payment_method,
        )
        logger.info(
            "会员订阅下单成功: user={}, plan_id={}, period={}, order={}, amount_cents={}, mode={}",
            current_user.id,
            request.plan_id,
            request.period,
            data.get("order_no"),
            data.get("amount"),
            data.get("mode"),
        )
        await audit.log(detail={
            "user_id": current_user.id,
            "plan_id": request.plan_id,
            "period": request.period,
            "payment_method": request.payment_method,
            "order_no": data.get("order_no"),
            "amount_cents": data.get("amount"),
            "mode": data.get("mode"),
        })
        return Response(code=200, success=True, message="订单创建成功，请前往支付", data=data)
    except ValueError as e:
        logger.warning(
            "会员订阅下单失败: user={}, plan_id={}, period={}, payment_method={}, error={}",
            current_user.id,
            request.plan_id,
            request.period,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "plan_id": request.plan_id,
                "period": request.period,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise BadRequestError(str(e)) from e
    except Exception as e:
        logger.warning(
            "会员订阅下单失败: user={}, plan_id={}, period={}, payment_method={}, error={}",
            current_user.id,
            request.plan_id,
            request.period,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "plan_id": request.plan_id,
                "period": request.period,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise


@router.post("/membership/cancel", response_model=Response[MembershipSetResponse],
             summary="取消续费")
async def cancel_membership(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.CONFIG_CHANGE,
        description="用户取消会员自动续费",
        level=AuditLevel.HIGH,
    )),
) -> Any:
    current_user.auto_renew = False
    await db.commit()
    logger.info(
        "会员自动续费取消: user={}, vip_level={}, vip_expire_at={}",
        current_user.id,
        current_user.vip_level,
        current_user.vip_expire_at,
    )
    await audit.log(detail={
        "user_id": current_user.id,
        "vip_level": current_user.vip_level,
        "vip_expire_at": str(current_user.vip_expire_at) if current_user.vip_expire_at else None,
        "auto_renew": False,
    })
    return Response(code=200, success=True, message="已取消自动续费，会员权益将持续至到期", data={
        "vip_level": current_user.vip_level,
        "vip_expire_at": str(current_user.vip_expire_at) if current_user.vip_expire_at else None,
        "auto_renew": False,
    })
