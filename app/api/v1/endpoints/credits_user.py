"""积分相关接口（用户端）

- GET  /credits/balance          查询余额
- GET  /credits/transactions     积分流水
- POST /credits/checkin          每日签到
- GET  /credits/checkin/status   签到状态
- GET  /credits/packs            积分包列表
- POST /credits/purchase         购买积分包
"""
from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, AuditLevel, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.exceptions import BadRequestError
from app.core.logger import logger
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.response import Response
from app.schemas.credit import (
    CreditBalanceResponse, CreditTransactionListResponse,
    CheckinStatusResponse, CheckinResponse, PurchasePackRequest,
    CreditPackResponse, PurchaseResponse,
)
from app.services.credit_service import credit_service

router = APIRouter()


@router.get("/credits/balance", response_model=Response[CreditBalanceResponse],
            summary="查询积分余额")
async def get_balance(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    data = await credit_service.get_balance(db, current_user.id)
    return Response(code=200, success=True, message="查询成功", data=data)


@router.get("/credits/transactions", response_model=Response[CreditTransactionListResponse],
            summary="积分流水")
async def get_transactions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    type: Optional[str] = Query(None, description="类型过滤"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    data = await credit_service.get_transactions(
        db, current_user.id, page=page, page_size=page_size, type_filter=type
    )
    return Response(code=200, success=True, message="查询成功", data=data)


@router.get("/credits/checkin/status", response_model=Response[CheckinStatusResponse],
            summary="签到状态")
async def checkin_status(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    data = await credit_service.get_checkin_status(db, current_user.id)
    return Response(code=200, success=True, message="查询成功", data=data)


@router.post("/credits/checkin", response_model=Response[CheckinResponse],
             summary="每日签到")
async def daily_checkin(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    try:
        data = await credit_service.checkin(db, current_user.id)
        return Response(code=200, success=True, message="签到成功", data=data)
    except ValueError as e:
        raise BadRequestError(str(e)) from e


@router.get("/credits/packs", response_model=Response[list[CreditPackResponse]],
            summary="积分包列表")
async def get_credit_packs(
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    data = await credit_service.get_credit_packs(db)
    return Response(code=200, success=True, message="查询成功", data=data)


@router.post("/credits/purchase", response_model=Response[PurchaseResponse],
             summary="购买积分包")
async def purchase_credit_pack(
    request: PurchasePackRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.PAYMENT,
        description="用户购买积分包",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    from app.services.payment_service import payment_service
    try:
        logger.info(
            "积分包下单开始: user={}, pack_id={}, payment_method={}",
            current_user.id,
            request.pack_id,
            request.payment_method,
        )
        data = await payment_service.create_payment(
            db, current_user.id,
            order_type="credit_pack",
            item_id=request.pack_id,
            payment_method=request.payment_method,
        )
        logger.info(
            "积分包下单成功: user={}, pack_id={}, order={}, amount_cents={}, mode={}",
            current_user.id,
            request.pack_id,
            data.get("order_no"),
            data.get("amount"),
            data.get("mode"),
        )
        await audit.log(detail={
            "user_id": current_user.id,
            "pack_id": request.pack_id,
            "payment_method": request.payment_method,
            "order_no": data.get("order_no"),
            "amount_cents": data.get("amount"),
            "mode": data.get("mode"),
        })
        return Response(code=200, success=True, message="订单创建成功，请前往支付", data=data)
    except ValueError as e:
        logger.warning(
            "积分包下单失败: user={}, pack_id={}, payment_method={}, error={}",
            current_user.id,
            request.pack_id,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "pack_id": request.pack_id,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise BadRequestError(str(e)) from e
    except Exception as e:
        logger.warning(
            "积分包下单失败: user={}, pack_id={}, payment_method={}, error={}",
            current_user.id,
            request.pack_id,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "pack_id": request.pack_id,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise
