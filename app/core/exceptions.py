"""自定义异常模块

定义业务异常类型，便于统一处理和错误码管理。
使用方法：
    from app.core.exceptions import NotFoundError, AuthenticationError

    raise NotFoundError("用户不存在")
    raise AuthenticationError("密码错误")
"""
from typing import Optional, Any, Dict


class AppException(Exception):
    """
    应用基础异常类

    所有业务异常都应继承此类。
    """
    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "服务器内部错误"

    def __init__(
        self,
        message: Optional[str] = None,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        detail: Optional[Any] = None,
    ):
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.detail = detail
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为响应字典"""
        result = {
            "code": self.status_code,
            "error_code": self.code,
            "message": self.message,
        }
        if self.detail:
            result["detail"] = self.detail
        return result


# ==================== 客户端错误（4xx） ====================

class BadRequestError(AppException):
    """请求参数错误（400）"""
    status_code = 400
    code = "BAD_REQUEST"
    message = "请求参数错误"


class ValidationError(AppException):
    """数据验证错误（400）"""
    status_code = 400
    code = "VALIDATION_ERROR"
    message = "数据验证失败"


class AuthenticationError(AppException):
    """认证失败（401）"""
    status_code = 401
    code = "AUTHENTICATION_FAILED"
    message = "认证失败"


class InvalidTokenError(AppException):
    """Token 无效（401）"""
    status_code = 401
    code = "INVALID_TOKEN"
    message = "无效的认证凭证"


class TokenExpiredError(AppException):
    """Token 过期（401）"""
    status_code = 401
    code = "TOKEN_EXPIRED"
    message = "认证凭证已过期"


class PermissionDeniedError(AppException):
    """权限不足（403）"""
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "权限不足"


class NotFoundError(AppException):
    """资源不存在（404）"""
    status_code = 404
    code = "NOT_FOUND"
    message = "资源不存在"


class ConflictError(AppException):
    """资源冲突（409）"""
    status_code = 409
    code = "CONFLICT"
    message = "资源冲突"


class DuplicateError(AppException):
    """资源重复（409）"""
    status_code = 409
    code = "DUPLICATE"
    message = "资源已存在"


class RateLimitError(AppException):
    """请求过于频繁（429）"""
    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"
    message = "请求过于频繁，请稍后再试"


# ==================== 服务端错误（5xx） ====================

class InternalError(AppException):
    """服务器内部错误（500）"""
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "服务器内部错误"


class DatabaseError(AppException):
    """数据库错误（500）"""
    status_code = 500
    code = "DATABASE_ERROR"
    message = "数据库操作失败"


class ExternalServiceError(AppException):
    """外部服务错误（502）"""
    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"
    message = "外部服务调用失败"


class ServiceUnavailableError(AppException):
    """服务不可用（503）"""
    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "服务暂时不可用"
