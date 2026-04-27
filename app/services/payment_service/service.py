"""支付核心服务 PaymentService

支持两种模式（由 `settings.PAYMENT_MODE` 决定）：
- mock: 本地开发模拟支付（直接成功）
- alipay: 对接支付宝真实/沙箱环境

支付流程：
1. 创建支付订单 → 返回支付链接/参数
2. 用户支付完成 → 支付宝异步通知回调
3. 后端验签 → 更新订单状态 → 发放积分/开通会员
"""
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.logger import logger
from app.core.timezone import now_utc
from app.models.membership import CreditPack, MembershipPlan, Order

from .alipay_client import build_alipay_client, gateway_url


class PaymentService:
    """支付核心服务"""

    def __init__(self):
        self._alipay_client = None

    @property
    def mode(self) -> str:
        return settings.PAYMENT_MODE

    def _get_alipay_client(self):
        """懒加载 AliPay 客户端（整个生命周期只创建一次）"""
        if self._alipay_client is not None:
            return self._alipay_client
        self._alipay_client = build_alipay_client(settings)
        return self._alipay_client

    # ==================== 创建支付 ====================

    async def create_payment(
        self,
        db: AsyncSession,
        user_id: int,
        order_type: str,
        item_id: int,
        period: str = "monthly",
        payment_method: str = "alipay",
    ) -> dict:
        """统一创建支付订单

        Args:
            order_type: "credit_pack" / "membership"
            period: 仅 membership 用 - "monthly" / "yearly"

        Returns:
            {
                "order_no": 订单号,
                "payment_url": 支付链接(mock 模式为本地模拟地址),
                "amount": 金额(分),
                ...
            }
        """
        if payment_method not in {"alipay", "wechat"}:
            logger.warning(
                "支付订单创建失败: user={}, type={}, item_id={}, period={}, payment_method={}, reason=invalid_payment_method",
                user_id,
                order_type,
                item_id,
                period,
                payment_method,
            )
            raise BadRequestError("支付方式无效")

        if order_type == "credit_pack":
            pack = await db.get(CreditPack, item_id)
            if not pack or not pack.is_active:
                logger.warning(
                    "支付订单创建失败: user={}, type={}, item_id={}, payment_method={}, reason=credit_pack_not_found_or_inactive",
                    user_id,
                    order_type,
                    item_id,
                    payment_method,
                )
                raise NotFoundError("积分包不存在或已下架")
            amount = pack.price
            credits_granted = pack.credits + pack.bonus_credits
            subject = f"积分包 - {pack.name}"
        elif order_type == "membership":
            if period not in {"monthly", "yearly"}:
                logger.warning(
                    "支付订单创建失败: user={}, type={}, item_id={}, period={}, payment_method={}, reason=invalid_period",
                    user_id,
                    order_type,
                    item_id,
                    period,
                    payment_method,
                )
                raise BadRequestError("订阅周期无效")

            plan = await db.get(MembershipPlan, item_id)
            if not plan or not plan.is_active:
                logger.warning(
                    "支付订单创建失败: user={}, type={}, item_id={}, period={}, payment_method={}, reason=membership_plan_not_found_or_inactive",
                    user_id,
                    order_type,
                    item_id,
                    period,
                    payment_method,
                )
                raise NotFoundError("会员方案不存在或已下架")
            amount = plan.price_yearly if period == "yearly" else plan.price_monthly
            credits_granted = plan.monthly_credits
            subject = f"会员订阅 - {plan.display_name}({'年付' if period == 'yearly' else '月付'})"
        else:
            logger.warning(
                "支付订单创建失败: user={}, type={}, item_id={}, period={}, payment_method={}, reason=unknown_order_type",
                user_id,
                order_type,
                item_id,
                period,
                payment_method,
            )
            raise BadRequestError(f"未知订单类型: {order_type}")

        prefix = "CP" if order_type == "credit_pack" else "MB"
        order_no = f"{prefix}{now_utc().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"

        order = Order(
            user_id=user_id,
            order_no=order_no,
            type=order_type,
            plan_id=item_id,
            amount=amount,
            credits_granted=credits_granted,
            status="pending",
            payment_method=payment_method,
            meta_data={
                "subject": subject,
                "period": period if order_type == "membership" else None,
            },
        )
        db.add(order)
        await db.flush()

        mode = self.mode
        if mode == "mock":
            payment_url = self._create_mock_payment_url(order_no)
        elif mode == "alipay":
            payment_url = self._create_alipay_payment_url(order_no, amount, subject)
        else:
            raise BadRequestError(f"未知支付模式: {mode}")

        await db.commit()

        logger.info(
            "支付订单创建成功: order_id={}, order_no={}, user={}, type={}, item_id={}, period={}, payment_method={}, amount_cents={}, credits_granted={}, mode={}",
            order.id,
            order_no,
            user_id,
            order_type,
            item_id,
            period if order_type == "membership" else None,
            payment_method,
            amount,
            credits_granted,
            mode,
        )

        return {
            "order_no": order_no,
            "payment_url": payment_url,
            "amount": amount,
            "amount_display": f"¥{amount / 100:.2f}",
            "subject": subject,
            "mode": mode,
        }

    # ==================== Mock 模式 ====================

    def _create_mock_payment_url(self, order_no: str) -> str:
        """Mock 模式：生成本地模拟支付链接

        优先使用 `settings.PUBLIC_API_BASE`(Docker/远程部署时的对外基址),
        未配置时回落到 127.0.0.1 + APP_PORT,方便本机开发。
        """
        base = settings.PUBLIC_API_BASE.rstrip("/") if settings.PUBLIC_API_BASE else (
            f"http://127.0.0.1:{settings.APP_PORT}"
        )
        return f"{base}/api/v1/payment/mock/pay?order_no={order_no}"

    async def mock_complete_payment(self, db: AsyncSession, order_no: str) -> dict:
        """Mock 模式:模拟支付成功(同样用条件 UPDATE 抢占首次履单权)"""
        logger.info("Mock 支付确认开始: order={}", order_no)
        order = await db.scalar(select(Order).where(Order.order_no == order_no))
        if not order:
            logger.warning("Mock 支付确认失败: order={} 不存在", order_no)
            raise NotFoundError("订单不存在")
        if order.status != "pending":
            logger.warning(
                "Mock 支付确认失败: order={}, user={}, status={}",
                order_no,
                order.user_id,
                order.status,
            )
            raise ConflictError(f"订单状态异常: {order.status}")

        # 条件更新作为"首次履单"守卫,多次点击 mock 支付页不会重复发积分
        result = await db.execute(
            update(Order)
            .where(Order.order_no == order_no, Order.status == "pending")
            .values()
        )
        if result.rowcount == 0:
            raise ConflictError("订单已被处理,请勿重复支付")
        await db.refresh(order)

        fulfill_result = await self._fulfill_order(db, order)
        await db.commit()
        logger.info(
            "Mock 支付确认成功: order={}, user={}, type={}, amount_cents={}, credits_granted={}",
            order.order_no,
            order.user_id,
            order.type,
            order.amount,
            order.credits_granted,
        )
        return fulfill_result

    # ==================== 支付宝模式 ====================

    def _create_alipay_payment_url(
        self, order_no: str, amount: int, subject: str
    ) -> str:
        """支付宝当面付 / 网页支付

        生成支付宝支付页面 URL（电脑网站支付 alipay.trade.page.pay）
        """
        if not settings.ALIPAY_APP_ID:
            raise ServiceUnavailableError("支付宝 APPID 未配置，请设置 ALIPAY_APP_ID")

        alipay = self._get_alipay_client()

        order_string = alipay.api_alipay_trade_page_pay(
            out_trade_no=order_no,
            total_amount=f"{amount / 100:.2f}",
            subject=subject,
            return_url=settings.ALIPAY_RETURN_URL or f"{settings.FRONTEND_URL}/payment/result",
            notify_url=settings.ALIPAY_NOTIFY_URL,
        )

        return f"{gateway_url(settings.ALIPAY_SANDBOX)}?{order_string}"

    async def verify_alipay_callback(self, data: dict) -> bool:
        """验证支付宝异步通知签名"""
        try:
            alipay = self._get_alipay_client()
        except ServiceUnavailableError:
            logger.error("python-alipay-sdk 未安装")
            return False

        signature = data.pop("sign", None)
        data.pop("sign_type", None)
        return alipay.verify(data, signature)

    async def handle_alipay_notify(self, db: AsyncSession, data: dict) -> str:
        """处理支付宝异步回调

        并发安全:
        - 支付宝在 24 小时内可能多次推送同一笔 notify(网络重试),如果读-判-写之间
          被另一条 notify 插入,就可能重复履单(重复发积分 / 重复开通会员)。
        - 解决方案:先做一次条件 `UPDATE ... WHERE status='pending'`,只有抢到
          首次置 paid 的连接才执行 `_fulfill_order`,`rowcount == 0` 表示已被其它
          请求处理过,直接返回 success(不再重跑业务)。

        Returns:
            "success" 或 "fail"(支付宝收到 "success" 才停止重试)
        """
        if not await self.verify_alipay_callback(data.copy()):
            logger.warning(
                "支付宝回调验签失败: order={}, trade_status={}, trade_no={}",
                data.get("out_trade_no"),
                data.get("trade_status"),
                data.get("trade_no"),
            )
            return "fail"

        trade_status = data.get("trade_status")
        order_no = data.get("out_trade_no")

        if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            logger.info("支付宝回调非成功状态: {}, order={}", trade_status, order_no)
            return "success"

        order = await db.scalar(select(Order).where(Order.order_no == order_no))
        if not order:
            logger.warning("支付宝回调订单不存在: {}", order_no)
            return "fail"

        if order.status == "paid":
            logger.info("订单已处理过: {}", order_no)
            return "success"

        total_amount = data.get("total_amount", "0")
        if int(float(total_amount) * 100) != order.amount:
            logger.warning(
                f"支付宝回调金额不匹配: expected={order.amount}, "
                f"got={total_amount}, order={order_no}"
            )
            return "fail"

        # 条件更新抢占"首次置 paid"权:只有一个并发连接能把 pending → paid
        trade_no = data.get("trade_no")
        result = await db.execute(
            update(Order)
            .where(Order.order_no == order_no, Order.status == "pending")
            .values(payment_id=trade_no)
        )
        if result.rowcount == 0:
            # 已被其它 notify 抢先处理,业务已由对方执行,这里直接 ACK 即可
            logger.info(
                "支付宝回调并发竞态中落败,订单已被其他请求履单: {}", order_no
            )
            await db.commit()
            return "success"

        # 刷新到最新状态再执行履单(此时仍是 pending, 状态由 _fulfill_order 置 paid)
        await db.refresh(order)
        order.payment_id = trade_no
        fulfill_result = await self._fulfill_order(db, order)
        await db.commit()
        logger.info(
            "支付宝回调履单成功: order={}, user={}, type={}, trade_no={}, amount_cents={}, result={}",
            order.order_no,
            order.user_id,
            order.type,
            trade_no,
            order.amount,
            fulfill_result,
        )

        return "success"

    # ==================== 订单完成处理 ====================

    async def _fulfill_order(self, db: AsyncSession, order: Order) -> dict:
        """完成订单：更新状态 + 发放积分/开通会员

        这是支付成功后的核心逻辑，mock 和 alipay 都会调用。
        """
        from app.services.credit_service import credit_service

        order.status = "paid"
        order.paid_at = now_utc().replace(tzinfo=None)

        if order.type == "credit_pack":
            tx = await credit_service.add_credits(
                db,
                order.user_id,
                amount=order.credits_granted,
                type="purchase",
                description=f"购买积分包，获得 {order.credits_granted} 积分",
                reference_id=order.order_no,
                source="payment",
            )
            logger.info(
                "积分包订单履约成功: order={}, user={}, amount_cents={}, credits={}, tx={}, balance_after={}",
                order.order_no,
                order.user_id,
                order.amount,
                order.credits_granted,
                tx.id,
                tx.balance_after,
            )

        elif order.type == "membership":
            plan = await db.get(MembershipPlan, order.plan_id)
            if plan:
                meta = order.meta_data or {}
                period = meta.get("period", "monthly")
                days = 365 if period == "yearly" else 30

                grant_tx = await credit_service.set_vip_level(
                    db,
                    order.user_id,
                    plan.name,
                    days,
                    source="payment",
                    reference_id=order.order_no,
                )

                # 月度积分已在 set_vip_level() 内部发放，此处不再重复

                logger.info(
                    "会员订单履约成功: order={}, user={}, plan={}, period={}, days={}, amount_cents={}, grant_tx={}, credits_granted={}",
                    order.order_no,
                    order.user_id,
                    plan.name,
                    period,
                    days,
                    order.amount,
                    grant_tx.id if grant_tx else None,
                    order.credits_granted,
                )

        return {
            "order_no": order.order_no,
            "status": "paid",
            "type": order.type,
            "credits_granted": order.credits_granted,
        }

    # ==================== 订单查询 ====================

    async def get_order_status(
        self, db: AsyncSession, order_no: str, user_id: int
    ) -> dict:
        """查询订单状态

        如果订单仍为 pending 且支付方式为 alipay，
        主动查询支付宝订单状态，已支付则自动完成订单。
        """
        order = await db.scalar(
            select(Order).where(
                Order.order_no == order_no,
                Order.user_id == user_id,
            )
        )
        if not order:
            raise NotFoundError("订单不存在")

        if order.status == "pending" and self.mode == "alipay":
            trade_result = await self._query_alipay_trade(order_no)
            if trade_result and trade_result.get("paid"):
                order.payment_id = trade_result.get("trade_no")
                await self._fulfill_order(db, order)
                await db.commit()
                logger.info("主动查询确认支付成功: order={}", order_no)

        return {
            "order_no": order.order_no,
            "type": order.type,
            "amount": order.amount,
            "amount_display": f"¥{order.amount / 100:.2f}",
            "status": order.status,
            "payment_method": order.payment_method,
            "paid_at": str(order.paid_at) if order.paid_at else None,
            "created_at": str(order.created_at),
        }

    async def _query_alipay_trade(self, order_no: str) -> dict | None:
        """主动查询支付宝交易状态

        调用 alipay.trade.query 接口。

        Returns:
            {"paid": True/False, "trade_no": "支付宝交易号"} 或 None
        """
        try:
            alipay = self._get_alipay_client()
        except ServiceUnavailableError:
            logger.error("python-alipay-sdk 未安装，无法查询支付宝订单")
            return None

        try:
            result = alipay.api_alipay_trade_query(out_trade_no=order_no)
            logger.info("支付宝主动查询: order={}, result={}", order_no, result)

            if result.get("code") == "10000":
                trade_status = result.get("trade_status")
                if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                    return {"paid": True, "trade_no": result.get("trade_no")}
                return {"paid": False}

            sub_code = result.get("sub_code", "")
            if sub_code != "ACQ.TRADE_NOT_EXIST":
                logger.warning("支付宝查询异常: {}", result)
            return {"paid": False}

        except Exception as e:
            logger.warning("支付宝主动查询失败: {}", e)
            return None

    async def get_user_orders(
        self,
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> dict:
        """用户订单列表"""
        from sqlalchemy import func as sqlfunc

        query = select(Order).where(Order.user_id == user_id)
        count_query = select(sqlfunc.count(Order.id)).where(Order.user_id == user_id)

        if status:
            query = query.where(Order.status == status)
            count_query = count_query.where(Order.status == status)

        total = await db.scalar(count_query) or 0

        result = await db.execute(
            query.order_by(Order.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        orders = result.scalars().all()

        items = [
            {
                "order_no": o.order_no,
                "type": o.type,
                "amount": o.amount,
                "amount_display": f"¥{o.amount / 100:.2f}",
                "credits_granted": o.credits_granted,
                "status": o.status,
                "payment_method": o.payment_method,
                "paid_at": str(o.paid_at) if o.paid_at else None,
                "created_at": str(o.created_at),
            }
            for o in orders
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


payment_service = PaymentService()
