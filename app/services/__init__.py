"""服务层模块

提供业务逻辑封装，将复杂业务从 API 层分离。

使用示例:
    from app.services import user_service

    # 在 API 端点中
    user = await user_service.register(db, user_in)
"""
from app.services.base import (
    BaseService,
    log_operation,
    services,
    ServiceRegistry,
)
from app.core.transaction import transactional
from app.services.user_service import user_service

__all__ = [
    # 基类和工具
    "BaseService",
    "ServiceRegistry",
    "log_operation",
    "services",
    "transactional",
    # 服务实例
    "user_service",
]
