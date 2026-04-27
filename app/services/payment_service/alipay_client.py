"""支付宝客户端相关纯函数

从 settings 构建 AliPay SDK 实例 / 拼接支付宝网关地址。
"""
from app.core.exceptions import ServiceUnavailableError

from .keys import format_private_key, format_public_key


def build_alipay_client(settings):
    """根据 settings 构建 AliPay SDK 实例

    懒导入 `alipay` 模块以避免未安装时阻断项目启动。
    """
    try:
        from alipay import AliPay
    except ImportError as e:
        raise ServiceUnavailableError(
            "请先安装 python-alipay-sdk: pip install python-alipay-sdk"
        ) from e

    return AliPay(
        appid=settings.ALIPAY_APP_ID,
        app_notify_url=settings.ALIPAY_NOTIFY_URL,
        app_private_key_string=format_private_key(settings.ALIPAY_PRIVATE_KEY),
        alipay_public_key_string=format_public_key(settings.ALIPAY_PUBLIC_KEY),
        sign_type="RSA2",
        debug=settings.ALIPAY_SANDBOX,
    )


def gateway_url(sandbox: bool) -> str:
    """返回支付宝开放网关地址"""
    if sandbox:
        return "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    return "https://openapi.alipay.com/gateway.do"
