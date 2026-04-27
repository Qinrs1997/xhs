"""AI 模块异常定义

继承项目已有的 AppException 体系，提供 AI 特定的异常类型。

使用方式：
    from app.ai.exceptions import AIRateLimitError

    raise AIRateLimitError("API 调用次数超限")
"""
from typing import Optional

from app.core.exceptions import ExternalServiceError


class AIError(ExternalServiceError):
    """AI 服务基础异常

    所有 AI 相关异常的基类
    """
    status_code = 502
    code = "AI_ERROR"
    message = "AI 服务调用失败"


class AIProviderError(AIError):
    """Provider 错误

    AI 服务商返回错误时抛出
    """
    code = "AI_PROVIDER_ERROR"
    message = "AI 服务商返回错误"

    def __init__(
        self,
        message: Optional[str] = None,
        provider: Optional[str] = None,
        original_error: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.provider = provider
        self.original_error = original_error


class AIRateLimitError(AIError):
    """速率限制

    API 调用频率超限时抛出
    """
    status_code = 429
    code = "AI_RATE_LIMIT"
    message = "AI 服务请求过于频繁，请稍后再试"

    def __init__(
        self,
        message: Optional[str] = None,
        retry_after: Optional[int] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after  # 建议等待秒数


class AIQuotaExceededError(AIError):
    """配额用尽

    API 配额/积分用尽时抛出
    """
    status_code = 402
    code = "AI_QUOTA_EXCEEDED"
    message = "AI 配额已用尽，请充值或升级套餐"


class AIContextTooLongError(AIError):
    """上下文过长

    会话上下文超出模型限制时抛出
    """
    status_code = 400
    code = "AI_CONTEXT_TOO_LONG"
    message = "会话上下文超出限制，请清空会话或开始新对话"

    def __init__(
        self,
        message: Optional[str] = None,
        current_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.current_tokens = current_tokens
        self.max_tokens = max_tokens


class AIInvalidRequestError(AIError):
    """无效请求

    请求参数无效或内容违规时抛出
    """
    status_code = 400
    code = "AI_INVALID_REQUEST"
    message = "AI 请求无效"


class AITimeoutError(AIError):
    """请求超时

    AI 服务响应超时时抛出
    """
    status_code = 504
    code = "AI_TIMEOUT"
    message = "AI 服务响应超时"


class AIServiceUnavailableError(AIError):
    """服务不可用

    AI 服务暂时不可用时抛出
    """
    status_code = 503
    code = "AI_SERVICE_UNAVAILABLE"
    message = "AI 服务暂时不可用"


class AIContentFilterError(AIError):
    """内容过滤

    请求或响应被内容安全过滤时抛出
    """
    status_code = 400
    code = "AI_CONTENT_FILTERED"
    message = "内容被安全策略过滤"
