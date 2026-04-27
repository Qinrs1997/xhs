"""搜索服务

支持多搜索引擎、Provider 动态切换、自动降级 Fallback 链、使用量追踪。

使用方式：
    from app.ai.services.search import SearchService

    service = SearchService(provider=get_provider("openai"))
    response = await service.search(SearchRequest(query="AI 发展趋势"))
"""
import time
from typing import Optional

from app.ai.services.base import BaseAIService
from app.ai.services.search.providers import (
    get_search_provider,
    get_provider_meta_list,
    BaseSearchProvider,
)
from app.ai.services.search.http_client import HTTPClientManager
from app.ai.providers.base import BaseProvider
from app.ai.config import ai_config
from app.ai.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.ai.schemas.common import AIMetadata, Usage
from app.core.logger import logger
from app.core.context import get_request_id


class SearchService(BaseAIService):
    """搜索服务

    支持多种搜索服务商：
    - DuckDuckGo（免费，无需 API Key）
    - Tavily（推荐，专为 AI 优化）
    - Serper（Google 搜索）
    - SearXNG（自托管元搜索引擎）

    功能：
    - 网页搜索（支持指定 Provider）
    - 搜索并用 AI 总结
    - 流式搜索回答
    - 自动降级 Fallback 链
    - 使用量追踪日志
    """

    service_name = "search"

    def __init__(
        self,
        provider: BaseProvider,
        search_provider_name: str = "duckduckgo",
    ):
        """
        初始化搜索服务

        Args:
            provider: AI Provider（用于生成总结）
            search_provider_name: 默认搜索提供商名称
        """
        super().__init__(provider)
        self._default_search_provider_name = search_provider_name
        self._search_providers: dict[str, BaseSearchProvider] = {}

        # Fallback 链配置（按优先级排列）
        self._fallback_chain: list[str] = self._build_fallback_chain()

    def _build_fallback_chain(self) -> list[str]:
        """构建 Fallback 降级链"""
        # 默认 Provider 排第一，其余 free Provider 跟后面
        default_name = (
            ai_config.search.provider
            if ai_config.search.enabled
            else self._default_search_provider_name
        )

        # 读取配置中的 fallback 列表（如果有）
        fallback = getattr(ai_config.search, "providers_fallback", None)
        if fallback:
            return fallback

        # 自动构建：默认 → duckduckgo → searxng
        chain = [default_name]
        for name in ["duckduckgo", "searxng"]:
            if name not in chain:
                chain.append(name)
        return chain

    def _get_search_provider(self, name: Optional[str] = None) -> BaseSearchProvider:
        """获取搜索提供商实例（带缓存）"""
        provider_name = name or (
            ai_config.search.provider
            if ai_config.search.enabled
            else self._default_search_provider_name
        )

        if provider_name not in self._search_providers:
            self._search_providers[provider_name] = get_search_provider(provider_name)
            logger.debug("搜索提供商已初始化: {}", provider_name)

        return self._search_providers[provider_name]

    @property
    def search_provider(self) -> BaseSearchProvider:
        """获取默认搜索提供商（向后兼容）"""
        return self._get_search_provider()

    async def close(self) -> None:
        """关闭服务资源"""
        await HTTPClientManager.close()

    # ==================== Provider 列表 API ====================

    @staticmethod
    def get_available_providers() -> list[dict]:
        """
        获取所有可用的搜索 Provider 元信息列表

        Returns:
            Provider 元信息列表，包含 name/display_name/description/is_default 等
        """
        default_name = (
            ai_config.search.provider
            if ai_config.search.enabled
            else "duckduckgo"
        )
        return get_provider_meta_list(current_default=default_name)

    # ==================== 主要接口 ====================

    async def search(
        self,
        request: SearchRequest,
        user_id: Optional[int] = None,
    ) -> SearchResponse:
        """
        执行搜索（支持指定 Provider + Fallback 降级）

        Args:
            request: 搜索请求（可包含 provider 指定搜索引擎）
            user_id: 用户 ID（用于使用量追踪）

        Returns:
            SearchResponse 包含搜索结果
        """
        start_time = time.time()

        # 确定搜索 Provider
        requested_provider = getattr(request, "provider", None)

        if requested_provider:
            # 用户指定了 Provider，不使用 Fallback
            results, used_provider_name = await self._search_single(
                request, requested_provider
            )
        else:
            # 使用 Fallback 链
            results, used_provider_name = await self._search_with_fallback(request)

        elapsed_ms = int((time.time() - start_time) * 1000)

        # 如果需要 AI 总结
        summary = None
        usage = None

        if request.include_summary and results:
            summary, usage = await self._generate_summary(request.query, results)

        # [SEARCH_USAGE] 使用量追踪日志
        logger.info(
            "[SEARCH_USAGE] user={}, provider={}, query='{}', results={}, time={}ms",
            user_id or "anonymous",
            used_provider_name,
            request.query,
            len(results),
            elapsed_ms,
        )

        return SearchResponse(
            query=request.query,
            results=results,
            summary=summary,
            sources_used=len(results),
            metadata=AIMetadata(
                model=ai_config.openai.chat_model if summary else "",
                provider=used_provider_name,
                usage=usage,
                latency_ms=elapsed_ms,
                request_id=get_request_id(),
            ),
        )

    async def _search_single(
        self,
        request: SearchRequest,
        provider_name: str,
    ) -> tuple[list[SearchResult], str]:
        """使用指定 Provider 搜索（不降级）"""
        search_provider = self._get_search_provider(provider_name)

        logger.info("执行搜索: query='{}', provider={}", request.query, provider_name)

        results = await search_provider.search(
            query=request.query,
            max_results=request.max_results,
            search_depth=request.search_depth,
        )
        return results, provider_name

    async def _search_with_fallback(
        self,
        request: SearchRequest,
    ) -> tuple[list[SearchResult], str]:
        """使用 Fallback 链搜索：主 Provider 失败时自动尝试下一个"""
        last_error: Optional[Exception] = None

        for provider_name in self._fallback_chain:
            try:
                search_provider = self._get_search_provider(provider_name)

                logger.info(
                    "执行搜索: query='{}', provider={}",
                    request.query, provider_name
                )

                results = await search_provider.search(
                    query=request.query,
                    max_results=request.max_results,
                    search_depth=request.search_depth,
                )

                if results:
                    return results, provider_name

                logger.warning(
                    "搜索 Provider {} 返回空结果，尝试下一个",
                    provider_name,
                )

            except Exception as e:
                last_error = e
                logger.warning(
                    "[SEARCH_FALLBACK] Provider {} 搜索失败: {}，尝试下一个",
                    provider_name, e,
                )
                continue

        # 所有 Provider 都失败了
        if last_error:
            logger.error("所有搜索 Provider 均失败，最后错误: {}", last_error)

        return [], self._fallback_chain[0] if self._fallback_chain else "unknown"

    async def _generate_summary(
        self,
        query: str,
        results: list[SearchResult],
    ) -> tuple[Optional[str], Optional[Usage]]:
        """
        根据搜索结果生成 AI 总结

        Args:
            query: 原始查询
            results: 搜索结果

        Returns:
            (总结内容, Token 使用量)
        """
        # 构建上下文
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"[{i}] {result.title}\n"
                f"链接: {result.url}\n"
                f"内容: {result.snippet or result.content or '无内容'}\n"
            )

        context = "\n".join(context_parts)

        # 构建提示词
        prompt = f"""基于以下搜索结果，回答用户的问题。请：
1. 综合多个来源的信息给出准确、全面的回答
2. 在回答中标注信息来源（使用 [1]、[2] 等标记）
3. 如果搜索结果不足以回答问题，请诚实说明

用户问题: {query}

搜索结果:
{context}

请用中文回答："""

        try:
            response = await self.provider.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个专业的搜索助手，擅长根据搜索结果提供准确、有引用的回答。"},
                    {"role": "user", "content": prompt},
                ],
                model=ai_config.openai.chat_model,
                temperature=0.3,
            )

            return response.content, Usage(**response.usage)

        except Exception as e:
            logger.error("生成搜索总结失败: {}", e)
            return None, None

    async def search_and_chat(
        self,
        query: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> dict:
        """
        搜索并聊天（联网对话）

        Args:
            query: 用户问题
            conversation_id: 会话 ID
            user_id: 用户 ID
            provider: 指定搜索引擎

        Returns:
            包含回答和搜索来源的字典
        """
        start_time = time.time()

        # 1. 执行搜索
        search_response = await self.search(
            SearchRequest(
                query=query,
                max_results=5,
                include_summary=False,
                provider=provider,
            ),
            user_id=user_id,
        )

        # 2. 构建带搜索上下文的对话
        if search_response.results:
            context_parts = ["以下是相关的网络搜索结果：\n"]
            for i, result in enumerate(search_response.results, 1):
                snippet = result.snippet[:200] if result.snippet else '无摘要'
                context_parts.append(
                    f"[{i}] **{result.title}**\n"
                    f"   链接: {result.url}\n"
                    f"   摘要: {snippet}...\n"
                )
            search_context = "\n".join(context_parts)

            system_prompt = f"""你是一个联网搜索助手。用户的问题需要结合网络搜索结果来回答。

{search_context}

请根据以上搜索结果回答用户问题。要求：
1. 综合多个来源给出准确回答
2. 在回答中使用 [1]、[2] 等标记引用来源
3. 如果搜索结果不足以完全回答问题，可以结合你的知识补充，但要说明哪些是来自搜索结果
4. 用中文回答"""
        else:
            system_prompt = "你是一个智能助手。搜索未返回结果，请根据你的知识回答用户问题。"

        # 3. 调用 AI 生成最终回答
        response = await self.provider.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            model=ai_config.openai.chat_model,
            temperature=0.5,
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        # 4. 构建响应
        return {
            "answer": response.content,
            "query": query,
            "sources": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                }
                for r in search_response.results
            ],
            "sources_count": len(search_response.results),
            "metadata": {
                "model": response.model,
                "provider": "openai",
                "usage": response.usage,
                "latency_ms": elapsed_ms,
                "search_provider": search_response.metadata.provider,
            },
        }

    async def search_stream(
        self,
        query: str,
        provider: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        """
        流式搜索并回答

        先返回搜索结果，再流式返回 AI 回答。

        Yields:
            dict: 事件数据
        """
        # 1. 先执行搜索
        search_response = await self.search(
            SearchRequest(
                query=query,
                max_results=5,
                include_summary=False,
                provider=provider,
            ),
            user_id=user_id,
        )

        # 发送搜索结果
        yield {
            "event": "sources",
            "data": {
                "sources": [
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                    }
                    for r in search_response.results
                ],
            },
        }

        # 2. 构建上下文并流式生成回答
        if search_response.results:
            context_parts = []
            for i, result in enumerate(search_response.results, 1):
                context_parts.append(
                    f"[{i}] {result.title}: {result.snippet or ''}"
                )
            search_context = "\n".join(context_parts)

            system_prompt = f"""基于以下搜索结果回答问题，使用 [1][2] 等标记引用来源：

{search_context}"""
        else:
            system_prompt = "搜索未返回结果，请根据知识回答。"

        # 3. 流式生成回答
        async for chunk in self.provider.chat_completion_stream(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            model=ai_config.openai.chat_model,
            temperature=0.5,
        ):
            yield {
                "event": "message",
                "data": {"content": chunk.content},
            }

            if chunk.is_final:
                yield {
                    "event": "done",
                    "data": {"finish_reason": chunk.finish_reason},
                }
