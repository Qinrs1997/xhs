"""AI 服务层

提供业务级别的 AI 服务封装。
"""
from app.ai.services.base import BaseAIService
from app.ai.services.chat import ChatService
from app.ai.services.summary import SummaryService
# 从重构后的 search 模块导入
from app.ai.services.search import SearchService, HTTPClientManager

__all__ = [
    "BaseAIService",
    "ChatService",
    "HTTPClientManager",
    "SearchService",
    "SummaryService",
]

