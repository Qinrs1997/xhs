"""SearXNG 搜索提供商

开源元搜索引擎，聚合 139+ 搜索引擎（Google/Bing/DuckDuckGo），自托管无限流。
需要自行部署：docker run -d -p 8080:8080 searxng/searxng
"""
from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.services.search.http_client import HTTPClientManager
from app.ai.schemas.search import SearchResult
from app.ai.config import ai_config
from app.ai.exceptions import AIProviderError
from app.core.logger import logger


class SearXNGProvider(BaseSearchProvider):
    """SearXNG 元搜索引擎提供商

    特点：
    - 聚合多个搜索引擎（Google/Bing/DuckDuckGo 等）
    - 自托管，无限流，无 API Key
    - 支持新闻、图片等多种搜索类型
    """

    name = "searxng"
    display_name = "SearXNG"
    description = "开源元搜索引擎，聚合 Google/Bing 等 139+ 搜索引擎，需自行部署"
    requires_api_key = False
    supports_news = True
    supports_images = True
    max_results_limit = 50

    def __init__(self):
        # 从配置读取 base_url，默认本地
        search_cfg = ai_config.search
        self.base_url = getattr(search_cfg, "searxng_base_url", "http://localhost:8080")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """
        执行 SearXNG 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
        """
        client = await HTTPClientManager.get_client()

        try:
            url = f"{self.base_url}/search"
            params = {
                "q": query,
                "format": "json",
                "language": kwargs.get("language", "zh-CN"),
                "pageno": 1,
                "safesearch": 0,
                "categories": kwargs.get("categories", "general"),
            }

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko)"
                ),
            }
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            results = []
            for i, item in enumerate(data.get("results", [])[:max_results]):
                score = max(0.1, 1.0 - i * 0.08)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=score,
                    published_date=item.get("publishedDate"),
                ))

            logger.info(
                "SearXNG 搜索完成: query='{}', results={}",
                query, len(results)
            )
            return results

        except Exception as e:
            logger.error("SearXNG 搜索失败: {}", e)
            raise AIProviderError(f"SearXNG 搜索失败: {e}") from e
