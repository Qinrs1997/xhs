"""支付核心服务子包

按职责拆为 4 个子模块，对外仍以 `payment_service.{PaymentService, payment_service}`
导出，保持 `from app.services.payment_service import payment_service` 向后兼容。

- `service.py`        — `PaymentService` 类（主编排器）
- `alipay_client.py`  — AliPay SDK 实例构建 + 网关地址
- `keys.py`           — PEM 私钥/公钥格式化

**测试注意**：旧代码中 `settings` 在 `payment_service.py` 顶层导入，
拆分后真实使用点在 `payment_service/service.py`。单元测试中的 monkeypatch
目标相应更新为 `app.services.payment_service.service.settings`。
"""
from app.core.config import settings  # BC re-export: tests monkeypatch this path

from .service import PaymentService, payment_service

__all__ = ["PaymentService", "payment_service", "settings"]
