"""AI 插件模块

提供 AI 能力的统一接口，包括：
- 聊天对话（支持流式）
- 内容总结
- 上下文管理
- 网页搜索（预留）
- 图像生成（预留）

使用方式：
    from app.ai import ai

    # 快速聊天
    response = await ai.chat("你好")

    # 带会话上下文的聊天
    response = await ai.chat("继续", conversation_id="xxx")

    # 文本总结
    summary = await ai.summarize("很长的文本...")
"""
from app.ai.config import ai_config
from app.ai.exceptions import (
    AIError,
    AIProviderError,
    AIRateLimitError,
    AIQuotaExceededError,
    AIContextTooLongError,
    AIInvalidRequestError,
)

# 延迟导入，避免循环引用
def get_ai():
    """获取 AI 服务门面实例"""
    from app.ai.facade import ai
    return ai

__all__ = [
    "AIContextTooLongError",
    # 异常
    "AIError",
    "AIInvalidRequestError",
    "AIProviderError",
    "AIQuotaExceededError",
    "AIRateLimitError",
    # 配置
    "ai_config",
    # 门面
    "get_ai",
]
