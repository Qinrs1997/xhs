"""AI 服务基类

定义所有 AI 服务的通用接口和行为。
"""
from abc import ABC
from typing import Optional

from app.ai.providers.base import BaseProvider
from app.ai.core.context import ContextManager
from app.ai.config import ai_config
from app.core.logger import logger


class BaseAIService(ABC):
    """AI 服务基类

    所有业务服务（聊天、总结、搜索等）的基类。
    提供 Provider 和 ContextManager 的统一访问。
    """

    # 服务名称
    service_name: str = "base"

    def __init__(
        self,
        provider: BaseProvider,
        context_manager: Optional[ContextManager] = None,
    ):
        """
        初始化服务

        Args:
            provider: AI Provider 实例
            context_manager: 上下文管理器（可选）
        """
        self.provider = provider
        self.context_manager = context_manager
        self._config = ai_config

        logger.debug("AI 服务已初始化: {}", self.service_name)

    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示词（子类可覆盖）"""
        return "你是一个有帮助的AI助手。请用中文回复。"

    def _build_metadata(
        self,
        model: str,
        usage: dict,
        latency_ms: int,
    ) -> dict:
        """构建响应元数据"""
        return {
            "model": model,
            "provider": self.provider.name,
            "usage": usage,
            "latency_ms": latency_ms,
        }
