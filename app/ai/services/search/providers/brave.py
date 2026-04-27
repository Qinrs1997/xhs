"""Brave Search 搜索提供商

独立搜索索引、隐私优先、AI 优化。
每月 $5 免费额度（约 1,000~2,000 次）。
注册获取 Key: https://brave.com/search/api/
"""
from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.services.search.http_client import HTTPClientManager
from app.ai.schemas.search import SearchResult
from app.ai.config import ai_config
from app.ai.exceptions import AIProviderError
from app.core.logger import logger

import httpx


class BraveSearchProvider(BaseSearchProvider):
    """Brave Search 搜索提供商

    特点：
    - 独立搜索索引（不依赖 Google/Bing）
    - 隐私优先，零数据保留
    - 每月 $5 免费额度
    - 支持 Web/News/Image/Video 搜索
    - 2026 年新增 LLM Context API，专为 AI 设计
    """

    name = "brave"
    display_name = "Brave Search"
    description = "独立搜索索引，隐私优先，每月免费 1000+ 次，搜索质量高"
    requires_api_key = True
    supports_news = True
    supports_images = True
    max_results_limit = 20

    API_BASE = "https://api.search.brave.com/res/v1"

    def __init__(self):
        # Brave API Key 优先用 brave 专属的，否则回退到通用搜索 api_key
        self.api_key = getattr(ai_config.search, "brave_api_key", "") or ai_config.search.api_key

    def validate_config(self) -> None:
        if not self.api_key:
            raise AIProviderError("Brave Search API Key 未配置，请在 settings.toml 设置 ai.search.brave_api_key")

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """
        执行 Brave Search 搜索

        Brave Web Search API:
          GET https://api.search.brave.com/res/v1/web/search
          Header: X-Subscription-Token: <API_KEY>
          Params: q, count, freshness, safesearch, country, search_lang

        Response 结构:
          { "web": { "results": [ { "url", "title", "description", "page_age", ... } ] } }
        """
        self.validate_config()

        client = await HTTPClientManager.get_client()

        try:
            url = f"{self.API_BASE}/web/search"
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self.api_key,
            }
            params = {
                "q": query,
                "count": min(max_results, 20),  # Brave 最多 20
                "safesearch": kwargs.get("safesearch", "moderate"),
                "search_lang": kwargs.get("search_lang", "zh"),
                "country": kwargs.get("country", "cn"),
                "text_decorations": False,  # 不要 HTML 标签
            }

            # 可选时效性过滤
            freshness = kwargs.get("freshness")
            if freshness:
                params["freshness"] = freshness  # pd=24h, pw=7d, pm=31d, py=1y

            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            results = []
            web_results = data.get("web", {}).get("results", [])

            for i, item in enumerate(web_results[:max_results]):
                score = max(0.1, 1.0 - i * 0.08)
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", ""),
                    score=score,
                    published_date=item.get("page_age"),
                ))

            logger.info(
                "Brave Search 完成: query='{}', results={}",
                query, len(results)
            )
            return results

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                logger.error("Brave Search API Key 无效或过期")
                raise AIProviderError("Brave Search API Key 无效") from e
            elif status == 429:
                logger.warning("Brave Search 超出免费额度限制")
                raise AIProviderError("Brave Search 超出用量限制，请稍后重试") from e
            else:
                logger.error("Brave Search 失败: HTTP {}", status)
                raise AIProviderError(f"Brave Search 失败: HTTP {status}") from e
        except Exception as e:
            logger.error("Brave Search 异常: {}", e)
            raise AIProviderError(f"Brave Search 异常: {e}") from e
