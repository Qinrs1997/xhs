"""AI 服务门面（Facade）

提供统一的 AI 服务入口，简化调用。

使用方式：
    from app.ai.facade import ai

    # 快速聊天
    response = await ai.chat("你好")

    # 带会话的聊天
    response = await ai.chat("继续", conversation_id="xxx")

    # 流式聊天
    async for chunk in ai.chat_stream("讲个故事"):
        print(chunk.content, end="")

    # 文本总结
    summary = await ai.summarize("很长的文本...")

    # 联网搜索
    result = await ai.search("2024年AI发展趋势")

    # 联网搜索并回答
    result = await ai.search_and_chat("什么是量子计算")

    # 应用关闭时
    await ai.close()
"""
from typing import Optional, AsyncIterator

from app.ai.config import ai_config
from app.ai.providers import get_provider
from app.ai.providers.base import BaseProvider
from app.ai.core.context import ContextManager, get_context_manager
from app.ai.services.chat import ChatService
from app.ai.services.summary import SummaryService
from app.ai.services.search import SearchService, HTTPClientManager
from app.ai.schemas.chat import ChatRequest, ChatResponse, ChatChunk
from app.ai.schemas.summary import SummaryRequest, SummaryResponse
from app.ai.schemas.search import SearchRequest, SearchResponse
from app.ai.schemas.image import ImageRequest, ImageResponse
from app.ai.services.image import ImageService
from app.ai.exceptions import AIError
from app.core.logger import logger


class AIFacade:
    """AI 服务门面

    提供统一的 AI 功能入口，隐藏内部复杂性。
    """

    def __init__(self):
        """初始化 AI 门面"""
        self._provider: Optional[BaseProvider] = None
        self._context_manager: Optional[ContextManager] = None
        self._chat_service: Optional[ChatService] = None
        self._summary_service: Optional[SummaryService] = None
        self._search_service: Optional[SearchService] = None
        self._image_service: Optional[ImageService] = None

        self._initialized = False

    def _ensure_initialized(self) -> None:
        """确保服务已初始化"""
        if self._initialized:
            return

        if not ai_config.enabled:
            raise AIError("AI 服务未启用，请在配置文件中设置 ai.enabled = true")

        # 初始化 Provider
        self._provider = get_provider(ai_config.default_provider)

        # 初始化 Context Manager
        self._context_manager = get_context_manager()

        # 初始化服务
        self._chat_service = ChatService(
            provider=self._provider,
            context_manager=self._context_manager,
        )
        self._summary_service = SummaryService(
            provider=self._provider,
            context_manager=self._context_manager,
        )
        self._search_service = SearchService(
            provider=self._provider,
        )
        self._image_service = ImageService(
            provider=self._provider,
        )

        self._initialized = True
        logger.info("AI 门面已初始化，Provider: {}", ai_config.default_provider)

    @property
    def provider(self) -> BaseProvider:
        """获取当前 Provider"""
        self._ensure_initialized()
        return self._provider

    @property
    def context_manager(self) -> ContextManager:
        """获取上下文管理器"""
        self._ensure_initialized()
        return self._context_manager

    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized

    async def close(self) -> None:
        """
        关闭 AI 服务，释放资源

        应在应用关闭时调用，确保：
        - HTTP 客户端正确关闭
        - 连接池释放
        """
        if self._initialized:
            # 关闭 HTTP 客户端（搜索服务使用）
            await HTTPClientManager.close()

            # 重置状态
            self._provider = None
            self._context_manager = None
            self._chat_service = None
            self._summary_service = None
            self._search_service = None
            self._image_service = None
            self._initialized = False

            logger.info("AI 门面已关闭")

    async def _resolve_system_prompt(
        self,
        system_prompt: Optional[str] = None,
        prompt_key: Optional[str] = None,
        prompt_variables: Optional[dict] = None,
        user_id: Optional[int] = None,
    ) -> Optional[str]:
        """解析系统提示词(异步版)

        `user_id` 会透传给 `prompts.get`,保证"用户私有 DB 模板"对当前调用可见。
        """
        if system_prompt:
            return system_prompt

        if prompt_key:
            try:
                from app.ai.prompts import prompts
                return await prompts.get(
                    prompt_key,
                    variables=prompt_variables or {},
                    user_id=user_id,
                )
            except Exception as e:
                logger.warning("获取提示词模板失败: {}, 错误: {}", prompt_key, e)
                return None

        return None

    async def create_conversation(
        self,
        prompt_key: Optional[str] = None,
        prompt_variables: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        title: Optional[str] = None,
        user_id: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        创建新会话

        Args:
            prompt_key: 提示词模板 key
            prompt_variables: 模板变量
            system_prompt: 自定义系统提示词（优先级高于 prompt_key）
            title: 会话标题
            user_id: 用户 ID
            metadata: 自定义元数据

        Returns:
            包含 conversation_id 的字典
        """
        self._ensure_initialized()

        # 解析系统提示词(把 user_id 透传,保证用户私有 DB 模板能被命中)
        final_system_prompt = await self._resolve_system_prompt(
            system_prompt=system_prompt,
            prompt_key=prompt_key,
            prompt_variables=prompt_variables,
            user_id=user_id,
        )

        context = await self._context_manager.get_or_create(
            conversation_id=None,  # 自动生成
            user_id=user_id,
            system_prompt=final_system_prompt,
        )

        from app.core.timezone import now_utc
        context_metadata = {
            "prompt_key": prompt_key,
            "title": title,
            "created_at": now_utc().isoformat(),
            **(metadata or {}),
        }

        # 预览提示词（前200字符）
        preview = final_system_prompt[:200] + "..." if final_system_prompt and len(final_system_prompt) > 200 else final_system_prompt

        return {
            "conversation_id": context.conversation_id,
            "created_at": context_metadata["created_at"],
            "prompt_key": prompt_key,
            "system_prompt_preview": preview,
            "metadata": context_metadata,
        }

    async def get_conversation_detail(
        self,
        conversation_id: str,
    ) -> Optional[dict]:
        """
        获取会话详情

        Args:
            conversation_id: 会话 ID

        Returns:
            会话详情字典，不存在返回 None
        """
        self._ensure_initialized()

        context = await self._context_manager.get(conversation_id)
        if not context:
            return None

        return {
            "conversation_id": context.conversation_id,
            "created_at": getattr(context, 'created_at', None),
            "updated_at": getattr(context, 'updated_at', None),
            "prompt_key": getattr(context, 'prompt_key', None),
            "system_prompt": context.system_prompt,
            "message_count": len(context.messages),
            "total_tokens": context.total_tokens,
            "metadata": getattr(context, 'metadata', None),
        }


    # ==================== 聊天功能 ====================

    async def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_key: Optional[str] = None,
        prompt_variables: Optional[dict] = None,
        user_id: Optional[int] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """
        快速聊天

        Args:
            message: 用户消息
            conversation_id: 会话 ID（可选，用于多轮对话）
            system_prompt: 系统提示词（可选，优先级最高）
            prompt_key: 提示词模板 key（可选，如 'chat/default'）
            prompt_variables: 提示词模板变量（可选）
            user_id: 用户 ID（可选）
            model: 模型名称（可选）
            temperature: 采样温度
            max_tokens: 最大 token 数

        Returns:
            ChatResponse 对象

        Examples:
            # 简单调用
            response = await ai.chat("你好")
            print(response.content)

            # 使用提示词模板
            response = await ai.chat(
                "我想咨询产品",
                prompt_key="roles/business/customer_service",
                prompt_variables={"company_name": "ABC科技"}
            )

            # 多轮对话
            r1 = await ai.chat("你好", conversation_id="conv1")
            r2 = await ai.chat("你刚才说什么？", conversation_id="conv1")
        """
        self._ensure_initialized()

        # 解析提示词:system_prompt > prompt_key > 默认;透传 user_id 以加载用户私有模板
        final_system_prompt = await self._resolve_system_prompt(
            system_prompt=system_prompt,
            prompt_key=prompt_key,
            prompt_variables=prompt_variables,
            user_id=user_id,
        )

        request = ChatRequest(
            message=message,
            conversation_id=conversation_id,
            system_prompt=final_system_prompt,
            prompt_key=prompt_key,
            prompt_variables=prompt_variables,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        return await self._chat_service.chat(request, user_id=user_id)


    async def chat_stream(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_key: Optional[str] = None,
        prompt_variables: Optional[dict] = None,
        user_id: Optional[int] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[ChatChunk]:
        """
        流式聊天

        Args:
            message: 用户消息
            conversation_id: 会话 ID
            system_prompt: 系统提示词
            prompt_key: 提示词模板 key
            prompt_variables: 提示词模板变量
            user_id: 用户 ID
            model: 模型名称
            temperature: 采样温度
            max_tokens: 最大 token 数

        Yields:
            ChatChunk 流式块
        """
        self._ensure_initialized()

        request = ChatRequest(
            message=message,
            conversation_id=conversation_id,
            system_prompt=system_prompt,
            prompt_key=prompt_key,
            prompt_variables=prompt_variables,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in self._chat_service.chat_stream(request, user_id=user_id):
            yield chunk

    async def chat_with_request(
        self,
        request: ChatRequest,
        user_id: Optional[int] = None,
    ) -> ChatResponse | AsyncIterator[ChatChunk]:
        """
        使用 ChatRequest 对象聊天

        Args:
            request: ChatRequest 对象
            user_id: 用户 ID

        Returns:
            根据 request.stream 返回 ChatResponse 或 AsyncIterator
        """
        self._ensure_initialized()

        if request.stream:
            return self._chat_service.chat_stream(request, user_id=user_id)
        else:
            return await self._chat_service.chat(request, user_id=user_id)

    # ==================== 总结功能 ====================

    async def summarize(
        self,
        text: str,
        style: str = "brief",
        max_length: Optional[int] = None,
        language: str = "zh",
    ) -> SummaryResponse:
        """
        文本总结

        Args:
            text: 要总结的文本
            style: 总结风格 (brief, detailed, bullet)
            max_length: 最大长度
            language: 输出语言

        Returns:
            SummaryResponse 对象

        Examples:
            summary = await ai.summarize("很长的文章内容...")
            print(summary.summary)

            # 要点总结
            summary = await ai.summarize(text, style="bullet")
            for point in summary.key_points:
                print(f"• {point}")
        """
        self._ensure_initialized()

        request = SummaryRequest(
            text=text,
            style=style,
            max_length=max_length,
            language=language,
        )

        return await self._summary_service.summarize_text(request)

    async def summarize_conversation(
        self,
        conversation_id: str,
        style: str = "brief",
    ) -> SummaryResponse:
        """
        会话总结

        Args:
            conversation_id: 会话 ID
            style: 总结风格

        Returns:
            SummaryResponse 对象
        """
        self._ensure_initialized()

        return await self._summary_service.summarize_conversation(
            conversation_id=conversation_id,
            style=style,
        )

    # ==================== 上下文管理 ====================

    async def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> dict:
        """
        获取会话历史

        Args:
            conversation_id: 会话 ID
            limit: 返回消息数量

        Returns:
            会话历史信息
        """
        self._ensure_initialized()
        return await self._chat_service.get_history(conversation_id, limit)

    async def clear_conversation(self, conversation_id: str) -> bool:
        """
        清空会话历史

        Args:
            conversation_id: 会话 ID

        Returns:
            是否成功
        """
        self._ensure_initialized()
        return await self._chat_service.clear_history(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        删除会话

        Args:
            conversation_id: 会话 ID

        Returns:
            是否成功
        """
        self._ensure_initialized()
        return await self._chat_service.delete_conversation(conversation_id)

    async def list_conversations(
        self,
        user_id: int,
        limit: int = 20,
    ) -> list[dict]:
        """
        列出用户的会话

        Args:
            user_id: 用户 ID
            limit: 返回数量

        Returns:
            会话列表
        """
        self._ensure_initialized()
        conversations = await self._context_manager.list_user_conversations(user_id, limit)
        return conversations

    # ==================== 工具方法 ====================

    def get_stats(self) -> dict:
        """获取 AI 服务统计信息"""
        self._ensure_initialized()
        return {
            "enabled": ai_config.enabled,
            "provider": ai_config.default_provider,
            "chat_enabled": ai_config.chat_enabled,
            "summary_enabled": ai_config.summary_enabled,
            "search_enabled": ai_config.search_enabled,
            "image_enabled": ai_config.image_enabled,
            "context_stats": self._context_manager.get_stats(),
        }

    async def health_check(self) -> dict:
        """
        健康检查

        Returns:
            健康状态信息
        """
        self._ensure_initialized()

        try:
            is_healthy = await self._provider.health_check()
            return {
                "status": "ok" if is_healthy else "degraded",
                "provider": ai_config.default_provider,
                "provider_healthy": is_healthy,
            }
        except Exception as e:
            return {
                "status": "error",
                "provider": ai_config.default_provider,
                "provider_healthy": False,
                "error": str(e),
            }

    # ==================== 搜索功能 ====================

    async def search(
        self,
        query: str,
        max_results: int = 5,
        include_summary: bool = True,
        provider: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> SearchResponse:
        """
        联网搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数
            include_summary: 是否包含 AI 总结
            provider: 搜索引擎（如 duckduckgo/tavily/serper/searxng）
            user_id: 用户 ID（用于使用量追踪）

        Returns:
            SearchResponse 包含搜索结果和可选的 AI 总结
        """
        self._ensure_initialized()

        request = SearchRequest(
            query=query,
            max_results=max_results,
            include_summary=include_summary,
            provider=provider,
        )

        return await self._search_service.search(request, user_id=user_id)

    async def search_and_chat(
        self,
        query: str,
        user_id: Optional[int] = None,
    ) -> dict:
        """
        联网搜索并用 AI 回答

        结合搜索结果和 AI 生成完整的回答，包含引用来源。

        Args:
            query: 用户问题
            user_id: 用户 ID

        Returns:
            dict 包含：
            - answer: AI 生成的回答
            - sources: 引用的来源列表
            - metadata: 元数据

        Examples:
            result = await ai.search_and_chat("什么是量子计算")
            print(result["answer"])
            print("来源：")
            for source in result["sources"]:
                print(f"  - {source['title']}: {source['url']}")
        """
        self._ensure_initialized()

        return await self._search_service.search_and_chat(
            query=query,
            user_id=user_id,
        )

    async def search_stream(
        self,
        query: str,
        user_id: Optional[int] = None,
    ):
        """
        流式联网搜索

        先返回搜索来源，再流式返回 AI 回答。

        Args:
            query: 用户问题
            user_id: 用户 ID

        Yields:
            dict: 包含 event 和 data
        """
        self._ensure_initialized()

        async for event in self._search_service.search_stream(query, user_id=user_id):
            yield event

    # ==================== 图像功能 ====================

    async def image_generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        style: Optional[str] = None,
        n: int = 1,
        negative_prompt: Optional[str] = None,
        image: Optional[str] = None,
        extra_params: Optional[dict] = None,
        user_id: Optional[int] = None,
        **kwargs
    ) -> ImageResponse:
        """
        生成图像

        Args:
            prompt: 图像描述
            model: 模型名称（如 black-forest-labs/FLUX.1-schnell）
            size: 尺寸（WxH，如 1024x1024），未指定时由模型默认值决定
            quality: 质量
            style: 风格
            n: 数量
            negative_prompt: 反向提示词
            image: 参考图（base64 或 URL，图生图/编辑）
            extra_params: 透传给模型的额外参数
            user_id: 用户 ID
            **kwargs: 其他参数

        Returns:
            ImageResponse 对象
        """
        self._ensure_initialized()

        request = ImageRequest(
            prompt=prompt,
            model=model,
            size=size,
            quality=quality,
            style=style,
            n=n,
            negative_prompt=negative_prompt,
            image=image,
            extra_params=extra_params,
        )

        return await self._image_service.generate_image(request, user_id=user_id, **kwargs)

    def get_image_models(self) -> dict:
        """
        获取可用的图片模型列表

        Returns:
            包含 default_model 和 models 列表的字典
        """
        self._ensure_initialized()
        from app.ai.services.image import ImageService
        return ImageService.get_available_models().model_dump()


# 全局 AI 门面实例
ai = AIFacade()
