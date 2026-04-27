"""Serper 搜索提供商

Google 搜索 API 代理。
需要 API Key: https://serper.dev
"""
from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.services.search.http_client import HTTPClientManager
from app.ai.schemas.search import SearchResult
from app.ai.config import ai_config
from app.ai.exceptions import AIProviderError
from app.core.logger import logger


class SerperProvider(BaseSearchProvider):
    """Serper 搜索提供商 (Google 搜索 API)

    特点：
    - Google 搜索结果
    - 支持多语言
    - 返回丰富的搜索结果结构
    """

    name = "serper"
    display_name = "Serper (Google)"
    description = "Google 搜索 API 代理，搜索质量高，需要 API Key"
    requires_api_key = True
    supports_news = True
    supports_images = True
    max_results_limit = 100

    def __init__(self):
        self.api_key = ai_config.search.api_key
        self.base_url = "https://google.serper.dev"

    def validate_config(self) -> None:
        if not self.api_key:
            raise AIProviderError("Serper API Key 未配置")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        language: str = "zh-cn",
        country: str = "cn",
        **kwargs
    ) -> list[SearchResult]:
        """
        执行 Serper (Google) 搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            language: 语言代码
            country: 国家代码
        """
        self.validate_config()

        client = await HTTPClientManager.get_client()

        try:
            url = f"{self.base_url}/search"
            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "q": query,
                "num": max_results,
                "hl": language,
                "gl": country,
            }

            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("organic", []):
                # 位置越靠前分数越高
                position = item.get("position", 10)
                score = max(0.1, 1.0 - (position - 1) * 0.1)

                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                    score=score,
                ))

            return results

        except Exception as e:
            logger.error("Serper 搜索失败: {}", e)
            raise AIProviderError(f"Serper 搜索失败: {e}") from e
