"""支付 API 端点

端点列表：
- POST /payment/create        创建支付订单
- GET  /payment/status        查询订单状态
- GET  /payment/orders        用户订单列表
- GET  /payment/mock/pay      Mock 模式模拟支付（仅开发环境）
- POST /payment/alipay/notify 支付宝异步回调
- GET  /payment/alipay/return 支付宝同步跳转
"""
from typing import Any, Literal, Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.audit import AuditAction, AuditLevel, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import BadRequestError
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.response import Response
from app.services.payment_service import payment_service

router = APIRouter()


# ==================== 响应 Schema ====================

class PaymentCreateResponse(BaseModel):
    order_no: str = ""
    payment_url: Optional[str] = None
    amount: Optional[int] = None

class PaymentStatusResponse(BaseModel):
    order_no: str = ""
    status: str = ""
    amount: int = 0
    paid_at: Optional[str] = None

class PaymentOrderListResponse(BaseModel):
    items: list = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


# ==================== 请求 Schema ====================

class CreatePaymentRequest(BaseModel):
    """创建支付请求"""
    type: Literal["credit_pack", "membership"] = Field(..., description="订单类型: credit_pack / membership")
    item_id: int = Field(..., gt=0, description="商品ID（积分包ID或会员方案ID）")
    period: Literal["monthly", "yearly"] = Field("monthly", description="订阅周期: monthly/yearly（仅会员用）")
    payment_method: Literal["alipay", "wechat"] = Field("alipay", description="支付方式: alipay/wechat")


# ==================== 创建支付 ====================

@router.post("/payment/create", response_model=Response[PaymentCreateResponse],
             summary="创建支付订单")
async def create_payment(
    request: CreatePaymentRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.PAYMENT,
        description="用户创建支付订单",
        level=AuditLevel.CRITICAL,
    )),
) -> Any:
    """
    创建支付订单，返回支付链接

    前端拿到 payment_url 后跳转即可：
    - mock 模式：直接访问链接完成模拟支付
    - alipay 模式：跳转支付宝收银台
    """
    try:
        logger.info(
            "支付订单创建接口开始: user={}, type={}, item_id={}, period={}, payment_method={}",
            current_user.id,
            request.type,
            request.item_id,
            request.period,
            request.payment_method,
        )
        data = await payment_service.create_payment(
            db, current_user.id,
            order_type=request.type,
            item_id=request.item_id,
            period=request.period,
            payment_method=request.payment_method,
        )
        logger.info(
            "支付订单创建接口成功: user={}, type={}, item_id={}, order={}, amount_cents={}, mode={}",
            current_user.id,
            request.type,
            request.item_id,
            data.get("order_no"),
            data.get("amount"),
            data.get("mode"),
        )
        await audit.log(detail={
            "user_id": current_user.id,
            "type": request.type,
            "item_id": request.item_id,
            "period": request.period if request.type == "membership" else None,
            "payment_method": request.payment_method,
            "order_no": data.get("order_no"),
            "amount_cents": data.get("amount"),
            "mode": data.get("mode"),
        })
        return Response(code=200, success=True, message="订单创建成功", data=data)
    except ValueError as e:
        logger.warning(
            "支付订单创建接口失败: user={}, type={}, item_id={}, period={}, payment_method={}, error={}",
            current_user.id,
            request.type,
            request.item_id,
            request.period,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "type": request.type,
                "item_id": request.item_id,
                "period": request.period,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise BadRequestError(str(e)) from e
    except Exception as e:
        logger.warning(
            "支付订单创建接口失败: user={}, type={}, item_id={}, period={}, payment_method={}, error={}",
            current_user.id,
            request.type,
            request.item_id,
            request.period,
            request.payment_method,
            e,
        )
        await audit.log(
            detail={
                "user_id": current_user.id,
                "type": request.type,
                "item_id": request.item_id,
                "period": request.period,
                "payment_method": request.payment_method,
            },
            success=False,
            error_message=str(e),
        )
        raise


# ==================== 查询订单 ====================

@router.get("/payment/status", response_model=Response[PaymentStatusResponse],
            summary="查询订单状态")
async def get_payment_status(
    order_no: str = Query(..., description="订单号"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """前端轮询订单状态，确认是否支付成功"""
    try:
        data = await payment_service.get_order_status(db, order_no, current_user.id)
        return Response(code=200, success=True, message="查询成功", data=data)
    except ValueError as e:
        raise BadRequestError(str(e)) from e


@router.get("/payment/orders", response_model=Response[PaymentOrderListResponse],
            summary="用户订单列表")
async def get_user_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="状态过滤: pending/paid/cancelled"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """查看我的订单列表"""
    data = await payment_service.get_user_orders(
        db, current_user.id, page=page, page_size=page_size, status=status
    )
    return Response(code=200, success=True, message="查询成功", data=data)


# ==================== Mock 模式 ====================

@router.get("/payment/mock/pay", response_class=HTMLResponse,
            summary="Mock 模拟支付页面")
async def mock_payment_page(
    order_no: str = Query(..., description="订单号"),
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    """
    Mock 模拟支付页面（仅开发环境可用）

    显示一个简单的支付页面，点击即完成支付
    """
    if settings.PAYMENT_MODE != "mock":
        return HTMLResponse("<h1>非 Mock 模式</h1>", status_code=403)

    # 查订单信息
    from sqlalchemy import select
    from app.models.membership import Order
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if not order:
        return HTMLResponse("<h1>订单不存在</h1>", status_code=404)
    if order.status != "pending":
        return HTMLResponse(f"<h1>订单已处理: {order.status}</h1>", status_code=400)

    amount_display = f"¥{order.amount/100:.2f}"
    meta = order.meta_data or {}
    subject = meta.get("subject", "未知商品")

    # 生成模拟支付页面
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>模拟支付</title>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #f0f2f5;
                   display: flex; align-items: center; justify-content: center;
                   min-height: 100vh; margin: 0; }}
            .card {{ background: white; border-radius: 16px; padding: 40px;
                     box-shadow: 0 4px 24px rgba(0,0,0,0.1); text-align: center;
                     max-width: 400px; width: 90%; }}
            .logo {{ font-size: 48px; margin-bottom: 16px; }}
            .title {{ font-size: 20px; color: #333; margin-bottom: 8px; }}
            .amount {{ font-size: 36px; font-weight: bold; color: #1677ff;
                       margin: 16px 0; }}
            .info {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
            .btn {{ background: linear-gradient(135deg, #1677ff, #0958d9);
                    color: white; border: none; padding: 14px 48px;
                    border-radius: 8px; font-size: 16px; cursor: pointer;
                    width: 100%; }}
            .btn:hover {{ opacity: 0.9; }}
            .btn:disabled {{ background: #ccc; cursor: not-allowed; }}
            .mode {{ background: #fff3cd; color: #856404; padding: 8px 16px;
                     border-radius: 4px; font-size: 12px; margin-top: 16px; }}
            .success {{ color: #52c41a; font-size: 48px; }}
        </style>
    </head>
    <body>
        <div class="card" id="payCard">
            <div class="logo">💳</div>
            <div class="title">{subject}</div>
            <div class="amount">{amount_display}</div>
            <div class="info">订单号: {order_no}</div>
            <button class="btn" id="payBtn" onclick="doPay()">确认支付</button>
            <div class="mode">🔧 开发模式 - 模拟支付</div>
        </div>
        <script>
            async function doPay() {{
                const btn = document.getElementById('payBtn');
                btn.disabled = true;
                btn.textContent = '处理中...';
                try {{
                    const resp = await fetch('/api/v1/payment/mock/confirm?order_no={order_no}', {{
                        method: 'POST'
                    }});
                    const data = await resp.json();
                    if (data.success) {{
                        document.getElementById('payCard').innerHTML = `
                            <div class="success">✅</div>
                            <div class="title">支付成功</div>
                            <div class="amount">{amount_display}</div>
                            <div class="info">${{data.message}}</div>
                            <div class="mode">3 秒后自动关闭...</div>
                        `;
                        setTimeout(() => {{ window.close(); }}, 3000);
                    }} else {{
                        btn.disabled = false;
                        btn.textContent = '重试';
                        alert(data.message || '支付失败');
                    }}
                }} catch (e) {{
                    btn.disabled = false;
                    btn.textContent = '重试';
                    alert('网络错误: ' + e.message);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.post("/payment/mock/confirm", response_model=Response[dict],
             summary="Mock 确认支付")
async def mock_confirm_payment(
    order_no: str = Query(..., description="订单号"),
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    """Mock 模式：确认支付成功（仅开发环境）"""
    if settings.PAYMENT_MODE != "mock":
        raise BadRequestError("非 Mock 模式")

    try:
        data = await payment_service.mock_complete_payment(db, order_no)
        logger.info("Mock 支付确认接口成功: order={}, result={}", order_no, data)
        return Response(code=200, success=True, message="支付成功", data=data)
    except ValueError as e:
        logger.warning("Mock 支付确认接口失败: order={}, error={}", order_no, e)
        raise BadRequestError(str(e)) from e
    except Exception as e:
        logger.warning("Mock 支付确认接口失败: order={}, error={}", order_no, e)
        raise


# ==================== 支付宝回调 ====================

@router.post("/payment/alipay/notify",
             summary="支付宝异步回调（支付宝服务器调用）")
async def alipay_notify(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    """
    支付宝异步通知处理

    支付宝在支付成功后调用此接口，需返回纯文本 "success"
    """
    form_data = await request.form()
    data = dict(form_data)

    logger.info("支付宝回调: order={}, status={}", data.get('out_trade_no'), data.get('trade_status'))

    result = await payment_service.handle_alipay_notify(db, data)
    return PlainTextResponse(result)


@router.get("/payment/alipay/return",
            summary="支付宝同步跳转")
async def alipay_return(
    request: Request,
) -> Any:
    """
    支付宝同步跳转（用户支付完后浏览器跳回）

    重定向到前端支付结果页
    """
    order_no = request.query_params.get("out_trade_no", "")
    frontend_url = settings.FRONTEND_URL
    return RedirectResponse(
        url=f"{frontend_url}/payment/result?order_no={order_no}"
    )
