"""Tavily 搜索提供商

专为 AI 优化的搜索 API，推荐使用。
需要 API Key: https://tavily.com
"""
from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.services.search.http_client import HTTPClientManager
from app.ai.schemas.search import SearchResult
from app.ai.config import ai_config
from app.ai.exceptions import AIProviderError
from app.core.logger import logger

import httpx


class TavilyProvider(BaseSearchProvider):
    """Tavily 搜索提供商

    特点：
    - 专为 AI 优化，返回结构化内容
    - 支持 basic/advanced 搜索深度
    - 可选获取完整页面内容
    """

    name = "tavily"
    display_name = "Tavily"
    description = "专为 AI 优化的搜索引擎，返回结构化内容，需要 API Key"
    requires_api_key = True
    supports_news = True
    supports_images = False
    max_results_limit = 20

    def __init__(self):
        # 仅做一次初始快照，真正调用前以 ai_config.search.api_key 为准
        # 这样管理员通过 PATCH /admin/ai/search/tavily 在线更新 key 时，
        # 不需要重启后端，下一次搜索就能使用新 key。
        self.api_key = ai_config.search.api_key
        self.base_url = "https://api.tavily.com"

    def validate_config(self) -> None:
        # 每次调用都从 ai_config 重新拉 key，与管理端"在线更新 key"保持同步
        self.api_key = ai_config.search.api_key
        if not self.api_key:
            raise AIProviderError("Tavily API Key 未配置")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_raw_content: bool = False,
        **kwargs
    ) -> list[SearchResult]:
        """
        执行 Tavily 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            search_depth: 搜索深度 (basic/advanced)
            include_raw_content: 是否包含完整页面内容
        """
        self.validate_config()

        client = await HTTPClientManager.get_client()

        try:
            url = f"{self.base_url}/search"
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": True,
                "include_raw_content": include_raw_content,
            }

            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    content=item.get("raw_content"),
                    score=item.get("score", 0),
                    published_date=item.get("published_date"),
                ))

            return results

        except httpx.HTTPStatusError as e:
            logger.error("Tavily 搜索失败: {}", e)
            raise AIProviderError(f"Tavily 搜索失败: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Tavily 搜索异常: {}", e)
            raise AIProviderError(f"Tavily 搜索异常: {e}") from e
