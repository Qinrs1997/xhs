"""中间件子包

按职责拆分为 3 个中间件 + 1 个 JSON 工具模块，对外 API 与旧单文件完全兼容：

- `request_tracing.py`        — RequestTracingMiddleware + REQUEST_ID_HEADER
- `operation_log.py`          — OperationLogMiddleware
- `response_normalization.py` — ResponseNormalizationMiddleware
- `_json.py`                  — orjson / stdlib json 的统一封装（内部使用）

保持导入路径兼容：
    from app.core.middleware import (
        RequestTracingMiddleware,
        OperationLogMiddleware,
        ResponseNormalizationMiddleware,
    )
"""
from .operation_log import OperationLogMiddleware
from .request_tracing import REQUEST_ID_HEADER, RequestTracingMiddleware
from .response_normalization import ResponseNormalizationMiddleware

__all__ = [
    "REQUEST_ID_HEADER",
    "OperationLogMiddleware",
    "RequestTracingMiddleware",
    "ResponseNormalizationMiddleware",
]
