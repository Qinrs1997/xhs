"""积分管理员接口

- POST /admin/credits/grant    管理员发放积分
- POST /admin/credits/deduct   管理员扣除积分
- PUT  /admin/membership/set   管理员设置会员等级
- GET  /admin/credits/stats    积分消耗统计
"""
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, AuditLevel, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.logger import logger
from app.api.deps import get_current_superuser
from app.models.user import User
from app.schemas.response import Response
from app.schemas.credit import (
    AdminCreditGrantRequest, AdminSetMembershipRequest,
    CreditOperationResponse, MembershipSetResponse, AdminCreditStatsResponse,
    AdminCreditUserListResponse, AdminCreditBatchAdjustRequest,
    AdminCreditBatchAdjustResponse,
)
from app.services.credit_service import credit_service, VIP_DISPLAY

router = APIRouter()


@router.get("/admin/credits/users", response_model=Response[AdminCreditUserListResponse],
            summary="管理员查询会员积分用户列表")
async def admin_credit_users(
    keyword: str | None = Query(None, description="用户名/邮箱/姓名关键字"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    logger.info(
        "管理员查询积分用户: admin={}, keyword={}, page={}, page_size={}",
        current_user.id,
        keyword,
        page,
        page_size,
    )
    data = await credit_service.get_admin_credit_users(
        db, keyword=keyword, page=page, page_size=page_size
    )
    return Response(code=200, success=True, message="查询成功", data=data)


@router.post("/admin/credits/grant", response_model=Response[CreditOperationResponse],
             summary="管理员发放积分")
async def admin_grant_credits(
    request: AdminCreditGrantRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.RECHARGE,
        description="管理员发放积分",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    amount = abs(request.amount)
    try:
        tx = await credit_service.admin_grant(
            db, request.user_id, amount, request.description, current_user.id
        )
        logger.info(
            "管理员发放积分成功: admin={}, target_user={}, amount={}, tx={}, balance_after={}, reason={}",
            current_user.id,
            request.user_id,
            tx.amount,
            tx.id,
            tx.balance_after,
            request.description.strip(),
        )
        await audit.log(detail={
            "admin_id": current_user.id,
            "target_user_id": request.user_id,
            "amount": tx.amount,
            "transaction_id": tx.id,
            "balance_after": tx.balance_after,
            "reason": request.description.strip(),
        })
    except Exception as e:
        logger.warning(
            "管理员发放积分失败: admin={}, target_user={}, amount={}, reason={}, error={}",
            current_user.id,
            request.user_id,
            amount,
            request.description.strip(),
            e,
        )
        await audit.log(
            detail={
                "admin_id": current_user.id,
                "target_user_id": request.user_id,
                "amount": amount,
                "reason": request.description.strip(),
            },
            success=False,
            error_message=str(e),
        )
        raise
    return Response(
        code=200, success=True, message="积分发放成功",
        data={
            "user_id": tx.user_id,
            "amount": tx.amount,
            "balance_after": tx.balance_after,
            "transaction_id": tx.id,
            "type": tx.type,
            "description": tx.description,
        },
    )


@router.post("/admin/credits/deduct", response_model=Response[CreditOperationResponse],
             summary="管理员扣除积分")
async def admin_deduct_credits(
    request: AdminCreditGrantRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.TRANSFER,
        description="管理员扣除积分",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    amount = -abs(request.amount)
    try:
        tx = await credit_service.admin_grant(
            db, request.user_id, amount, request.description, current_user.id
        )
        logger.info(
            "管理员扣除积分成功: admin={}, target_user={}, amount={}, tx={}, balance_after={}, reason={}",
            current_user.id,
            request.user_id,
            tx.amount,
            tx.id,
            tx.balance_after,
            request.description.strip(),
        )
        await audit.log(detail={
            "admin_id": current_user.id,
            "target_user_id": request.user_id,
            "amount": tx.amount,
            "transaction_id": tx.id,
            "balance_after": tx.balance_after,
            "reason": request.description.strip(),
        })
    except Exception as e:
        logger.warning(
            "管理员扣除积分失败: admin={}, target_user={}, amount={}, reason={}, error={}",
            current_user.id,
            request.user_id,
            amount,
            request.description.strip(),
            e,
        )
        await audit.log(
            detail={
                "admin_id": current_user.id,
                "target_user_id": request.user_id,
                "amount": amount,
                "reason": request.description.strip(),
            },
            success=False,
            error_message=str(e),
        )
        raise
    return Response(
        code=200, success=True, message="积分扣除成功",
        data={
            "user_id": tx.user_id,
            "amount": tx.amount,
            "balance_after": tx.balance_after,
            "transaction_id": tx.id,
            "type": tx.type,
            "description": tx.description,
        },
    )


@router.post("/admin/credits/batch-adjust", response_model=Response[AdminCreditBatchAdjustResponse],
             summary="管理员批量发放/扣除积分")
async def admin_batch_adjust_credits(
    request: AdminCreditBatchAdjustRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.TRANSFER,
        description="管理员批量调整积分",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    try:
        transactions = await credit_service.admin_adjust_many(
            db,
            user_ids=request.user_ids,
            amount=request.amount,
            reason=request.description,
            admin_id=current_user.id,
        )
    except Exception as e:
        logger.warning(
            "管理员批量积分调整失败: admin={}, targets={}, amount={}, reason={}, error={}",
            current_user.id,
            request.user_ids,
            request.amount,
            request.description.strip(),
            e,
        )
        await audit.log(
            detail={
                "admin_id": current_user.id,
                "target_user_ids": request.user_ids,
                "amount": request.amount,
                "reason": request.description.strip(),
            },
            success=False,
            error_message=str(e),
        )
        raise
    data = {
        "updated_count": len(transactions),
        "amount": request.amount,
        "description": request.description.strip(),
        "items": [
            {
                "user_id": tx.user_id,
                "amount": tx.amount,
                "balance_after": tx.balance_after,
                "transaction_id": tx.id,
            }
            for tx in transactions
        ],
    }
    logger.info(
        "管理员批量积分调整成功: admin={}, updated_count={}, amount={}, tx_ids={}, reason={}",
        current_user.id,
        len(transactions),
        request.amount,
        [tx.id for tx in transactions[:20]],
        request.description.strip(),
    )
    await audit.log(detail={
        "admin_id": current_user.id,
        "target_user_ids": request.user_ids,
        "amount": request.amount,
        "updated_count": len(transactions),
        "transaction_ids": [tx.id for tx in transactions[:100]],
        "reason": request.description.strip(),
    })
    return Response(code=200, success=True, message="积分调整成功", data=data)


@router.put("/admin/membership/set", response_model=Response[MembershipSetResponse],
            summary="管理员设置会员等级")
async def admin_set_membership(
    request: AdminSetMembershipRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.CONFIG_CHANGE,
        description="管理员设置会员等级",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    if request.expire_at:
        from app.core.timezone import now_utc
        delta = request.expire_at - now_utc().replace(tzinfo=None)
        days = max(int(delta.total_seconds() / 86400), 1)
    else:
        days = request.days

    try:
        grant_tx = await credit_service.set_vip_level(
            db,
            request.user_id,
            request.vip_level,
            days,
            source="admin",
            reference_id=str(current_user.id),
            operator_id=current_user.id,
        )
        logger.info(
            "管理员设置会员成功: admin={}, target_user={}, vip_level={}, days={}, expire_at={}, grant_tx={}",
            current_user.id,
            request.user_id,
            request.vip_level,
            days,
            request.expire_at,
            grant_tx.id if grant_tx else None,
        )
        await audit.log(detail={
            "admin_id": current_user.id,
            "target_user_id": request.user_id,
            "vip_level": request.vip_level,
            "days": days,
            "expire_at": str(request.expire_at) if request.expire_at else None,
            "grant_transaction_id": grant_tx.id if grant_tx else None,
        })
    except Exception as e:
        logger.warning(
            "管理员设置会员失败: admin={}, target_user={}, vip_level={}, days={}, expire_at={}, error={}",
            current_user.id,
            request.user_id,
            request.vip_level,
            days,
            request.expire_at,
            e,
        )
        await audit.log(
            detail={
                "admin_id": current_user.id,
                "target_user_id": request.user_id,
                "vip_level": request.vip_level,
                "days": days,
                "expire_at": str(request.expire_at) if request.expire_at else None,
            },
            success=False,
            error_message=str(e),
        )
        raise
    return Response(
        code=200, success=True,
        message=f"已设置用户 {request.user_id} 为 {VIP_DISPLAY.get(request.vip_level)} 会员",
        data={"user_id": request.user_id, "vip_level": request.vip_level},
    )



@router.get("/admin/credits/stats", response_model=Response[AdminCreditStatsResponse],
            summary="积分消耗统计")
async def admin_credits_stats(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
) -> Any:
    logger.info("管理员查询积分统计: admin={}", current_user.id)
    data = await credit_service.get_admin_stats(db)
    return Response(code=200, success=True, message="查询成功", data=data)
