"""搜索 Schema（预留）

定义网页搜索相关的请求和响应模型。
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.common import AIMetadata


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str = Field(
        description="搜索查询",
        min_length=1,
        max_length=500,
    )
    max_results: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最大结果数量"
    )
    include_summary: bool = Field(
        default=True,
        description="是否包含 AI 生成的搜索结果总结"
    )
    search_depth: str = Field(
        default="basic",
        description="搜索深度：basic=快速, advanced=深度"
    )
    provider: Optional[str] = Field(
        default=None,
        description="搜索引擎（如 duckduckgo/tavily/serper/searxng），不指定则用默认"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "2024年人工智能发展趋势",
                "max_results": 5,
                "include_summary": True,
                "provider": "duckduckgo",
            }
        }
    )


class SearchResult(BaseModel):
    """搜索结果项"""
    title: str = Field(
        description="标题"
    )
    url: str = Field(
        description="链接"
    )
    snippet: str = Field(
        description="摘要片段"
    )
    content: Optional[str] = Field(
        default=None,
        description="完整内容（如果抓取成功）"
    )
    score: Optional[float] = Field(
        default=None,
        description="相关性分数"
    )
    published_date: Optional[str] = Field(
        default=None,
        description="发布日期"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "2024年AI发展十大趋势",
                "url": "https://example.com/ai-trends-2024",
                "snippet": "本文探讨了2024年人工智能领域的十大发展趋势...",
                "score": 0.95,
            }
        }
    )


class SearchResponse(BaseModel):
    """搜索响应"""
    query: str = Field(
        description="原始查询"
    )
    results: list[SearchResult] = Field(
        description="搜索结果列表"
    )
    summary: Optional[str] = Field(
        default=None,
        description="AI 生成的搜索结果总结"
    )
    sources_used: int = Field(
        description="使用的来源数量"
    )
    search_id: Optional[int] = Field(
        default=None,
        description="搜索历史记录 ID（用于关联后续生成任务）"
    )
    metadata: AIMetadata = Field(
        description="响应元数据"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "2024年人工智能发展趋势",
                "results": [
                    {
                        "title": "2024年AI发展十大趋势",
                        "url": "https://example.com/article1",
                        "snippet": "本文探讨了...",
                    }
                ],
                "summary": "根据搜索结果,2024年AI发展的主要趋势包括...",
                "sources_used": 5,
                "metadata": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                },
            }
        }
    )
