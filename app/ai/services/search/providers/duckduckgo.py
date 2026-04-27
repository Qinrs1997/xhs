"""DuckDuckGo 搜索提供商

使用 ddgs 库，提供真正的网页搜索结果。
免费搜索，无需 API Key。
"""
import asyncio

from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.schemas.search import SearchResult
from app.core.logger import logger


class DuckDuckGoProvider(BaseSearchProvider):
    """DuckDuckGo 搜索提供商

    特点：
    - 免费使用，无需 API Key
    - 使用 duckduckgo-search 库获取真实搜索结果
    - 支持中文搜索（region=cn-zh）
    - 支持新闻搜索
    """

    name = "duckduckgo"
    display_name = "DuckDuckGo"
    description = "免费搜索引擎，无需 API Key，支持全球搜索"
    requires_api_key = False
    supports_news = True
    supports_images = True
    max_results_limit = 20

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """
        执行 DuckDuckGo 搜索

        使用 ddgs 库的 text() 方法，通过 asyncio.to_thread() 包装为异步。
        """
        region = kwargs.get("region", "cn-zh")

        try:
            raw_results = await asyncio.to_thread(
                self._search_sync, query, max_results, region
            )

            results = []
            for i, item in enumerate(raw_results):
                score = max(0.1, 1.0 - i * 0.1)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", ""),
                    score=score,
                ))

            logger.info(
                "DuckDuckGo 搜索完成: query='{}', results={}",
                query, len(results)
            )
            return results

        except Exception as e:
            logger.error("DuckDuckGo 搜索失败: {}", e)
            return []

    @staticmethod
    def _search_sync(
        query: str,
        max_results: int = 5,
        region: str = "cn-zh",
    ) -> list[dict]:
        """同步搜索（在线程池中执行）"""
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(
                query=query,
                region=region,
                max_results=max_results,
            ))
        return results
