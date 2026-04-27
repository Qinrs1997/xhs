"""AI Schema 层

定义 AI 模块的 Pydantic 数据模型。
"""
from app.ai.schemas.common import (
    Message,
    Usage,
    AIMetadata,
)
from app.ai.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatChunk,
    ChatStreamResponse,
)
from app.ai.schemas.summary import (
    SummaryRequest,
    SummaryResponse,
)
from app.ai.schemas.search import (
    SearchRequest,
    SearchResult,
    SearchResponse,
)
from app.ai.schemas.image import (
    ImageRequest,
    ImageResponse,
)

__all__ = [
    "AIMetadata",
    "ChatChunk",
    # Chat
    "ChatRequest",
    "ChatResponse",
    "ChatStreamResponse",
    # Image
    "ImageRequest",
    "ImageResponse",
    # Common
    "Message",
    # Search
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    # Summary
    "SummaryRequest",
    "SummaryResponse",
    "Usage",
]
