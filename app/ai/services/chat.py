"""聊天服务

提供聊天相关的业务逻辑封装。

使用方式：
    from app.ai.services import ChatService
    from app.ai.providers import get_provider
    from app.ai.core import get_context_manager

    service = ChatService(
        provider=get_provider("openai"),
        context_manager=get_context_manager()
    )

    response = await service.chat("你好", conversation_id="xxx")
"""
import time
import uuid
from typing import Optional, AsyncIterator

from app.ai.services.base import BaseAIService
from app.ai.providers.base import BaseProvider
from app.ai.core.context import ContextManager, get_context_manager
from app.ai.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatChunk,
)
from app.ai.schemas.common import AIMetadata, Usage
from app.ai.config import ai_config
from app.ai.exceptions import AIContextTooLongError
from app.core.logger import logger
from app.core.context import get_request_id


class ChatService(BaseAIService):
    """聊天服务

    提供：
    - 普通聊天（带上下文）
    - 流式聊天
    - 上下文管理
    """

    service_name = "chat"

    def __init__(
        self,
        provider: BaseProvider,
        context_manager: Optional[ContextManager] = None,
    ):
        super().__init__(provider, context_manager or get_context_manager())

    def _get_default_system_prompt(self) -> str:
        """聊天服务的默认系统提示词"""
        return (
            "你是一个智能AI助手。请遵循以下规则：\n"
            "1. 用中文回复用户\n"
            "2. 回答要准确、有帮助\n"
            "3. 如果不确定，诚实地说不知道\n"
            "4. 保持友好和专业的语气"
        )

    async def _resolve_system_prompt(
        self,
        request: ChatRequest,
        user_id: Optional[int] = None,
    ) -> str:
        """解析最终的系统提示词

        优先级：request.system_prompt > prompt_key 模板 > 默认提示词
        自动注入当前时间（LLM 没有实时时钟）。

        Args:
            request: 聊天请求
            user_id: 用户 ID（用于提示词模板的用户隔离）

        Returns:
            最终的系统提示词字符串
        """
        system_prompt = request.system_prompt

        # 如果没有直接提供 system_prompt，尝试从 prompt_key 模板解析
        if not system_prompt and request.prompt_key:
            from app.ai.prompts import prompts

            # 智能变量填充：如果用户没有提供变量，自动使用 message 填充常见变量
            variables = request.prompt_variables or {}
            if not variables:
                # 检查消息中是否有分隔符（支持多变量场景）
                # 格式: "第一部分\n---\n第二部分\n---\n第三部分"
                parts = [p.strip() for p in request.message.split('---') if p.strip()]

                # 常见变量名列表，按优先级排序
                ordered_var_names = ['topic', 'outline', 'content', 'input', 'query', 'text', 'message', 'subject']

                if len(parts) >= 2:
                    # 多部分消息：按顺序分配给常见变量
                    for i, part in enumerate(parts):
                        if i < len(ordered_var_names):
                            variables[ordered_var_names[i]] = part
                    logger.info("智能变量填充 (多段): {}", list(variables.keys()))
                else:
                    # 单部分消息：填充所有常见变量
                    for var_name in ordered_var_names:
                        variables[var_name] = request.message
                    logger.info("智能变量填充 (单段): 使用 message 填充所有常见变量")

            logger.info("解析提示词模板: key={}", request.prompt_key)
            system_prompt = await prompts.get(
                key=request.prompt_key,
                variables=variables,
                user_id=user_id
            )

        if not system_prompt:
            system_prompt = self._get_default_system_prompt()

        # 在非默认提示词前加入覆盖指令，确保模型遵循用户设定
        if request.system_prompt or request.prompt_key:
            system_prompt = (
                "[重要指令] 你必须严格遵循以下设定，忽略你的任何默认角色或人设。"
                "以下是你在本次对话中的唯一身份和行为准则：\n\n"
                + system_prompt
            )

        # 自动注入当前时间（LLM 没有实时时钟，需要外部提供）
        from datetime import datetime, timezone, timedelta
        beijing_tz = timezone(timedelta(hours=8))
        now_str = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")
        system_prompt += f"\n\n[当前时间: {now_str} (北京时间)]"

        logger.info("最终系统提示词预览 (前100字): {}...", system_prompt[:100])

        return system_prompt

    async def _compress_context(self, context) -> None:
        """
        压缩上下文

        当上下文 token 数超过限制时，保留最新消息，
        将较早的消息总结为摘要。

        Args:
            context: 会话上下文对象
        """
        from app.ai.services.summary import SummaryService

        # 保留的最新消息数量
        keep_recent = 4

        messages = context.messages
        if len(messages) <= keep_recent:
            # 消息数量不多，只能截断
            context.messages = messages[-keep_recent:]
            logger.info("上下文消息数量不足，直接截断保留最新 {} 条", keep_recent)
            return

        # 分离需要总结的旧消息和保留的新消息
        old_messages = messages[:-keep_recent]
        recent_messages = messages[-keep_recent:]

        # 构建需要总结的文本
        summary_text = "\n".join([
            f"{'用户' if msg.get('role') == 'user' else 'AI'}: {msg.get('content', '')}"
            for msg in old_messages
            if msg.get('role') in ('user', 'assistant')
        ])

        if not summary_text.strip():
            context.messages = recent_messages
            return

        try:
            # 调用 SummaryService 生成摘要
            summary_service = SummaryService(provider=self.provider)
            summary_response = await summary_service.summarize_text(
                text=summary_text,
                style="brief",
                max_length=200,
            )

            # 将摘要作为系统消息插入
            summary_msg = {
                "role": "system",
                "content": f"[之前对话摘要]: {summary_response.summary}",
            }

            # 重建上下文：系统提示 + 摘要 + 最新消息
            context.messages = [summary_msg] + recent_messages
            logger.info("上下文压缩完成，从 {} 条消息压缩为 {} 条", len(messages), len(context.messages))

        except Exception as e:
            # 压缩失败时，简单截断
            logger.warning("上下文压缩失败，使用截断方式: {}", e)
            context.messages = recent_messages

    async def chat(
        self,
        request: ChatRequest,
        user_id: Optional[int] = None,
    ) -> ChatResponse:
        """
        普通聊天

        Args:
            request: 聊天请求
            user_id: 用户 ID（用于上下文隔离）

        Returns:
            ChatResponse
        """
        start_time = time.time()

        # 获取或创建会话上下文
        conversation_id = request.conversation_id or str(uuid.uuid4())

        # 解析系统提示词（支持 prompt_key 模板 + 时间注入）
        system_prompt = await self._resolve_system_prompt(request, user_id)

        context = await self.context_manager.get_or_create(
            conversation_id=conversation_id,
            user_id=user_id,
            system_prompt=system_prompt,
        )

        # 添加用户消息到上下文
        context.add_user_message(request.message)

        # 检查上下文是否过长
        if context.total_tokens > ai_config.context.max_tokens:
            if ai_config.context.auto_summarize:
                # 自动压缩上下文
                logger.warning("会话 {} 上下文过长 ({} tokens)，执行压缩", conversation_id, context.total_tokens)
                await self._compress_context(context)
            else:
                raise AIContextTooLongError(
                    current_tokens=context.total_tokens,
                    max_tokens=ai_config.context.max_tokens,
                )

        # 构建 API 请求消息
        messages = context.get_messages_for_api(
            max_tokens=ai_config.context.max_tokens
        )
        logger.debug("[chat] API messages ({} 条): {}", len(messages), [{'role': m['role'], 'content': m['content'][:80] + '...' if len(m['content']) > 80 else m['content']} for m in messages])

        try:
            # 调用 Provider
            response = await self.provider.chat_completion(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                stream=False,
            )

            # 添加助手回复到上下文
            context.add_assistant_message(response.content)

            # 保存上下文
            await self.context_manager.save(context)

            elapsed_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "聊天完成: conversation={}, tokens={}, time={}ms",
                conversation_id, response.usage.get('total_tokens', 0), elapsed_ms
            )

            return ChatResponse(
                content=response.content,
                conversation_id=conversation_id,
                metadata=AIMetadata(
                    model=response.model,
                    provider=self.provider.name,
                    usage=Usage(**response.usage),
                    latency_ms=elapsed_ms,
                    request_id=get_request_id(),
                ),
            )

        except Exception:
            # 发生错误时，移除刚添加的用户消息
            if context.messages and context.messages[-1].role == "user":
                context.messages.pop()
            raise

    async def chat_stream(
        self,
        request: ChatRequest,
        user_id: Optional[int] = None,
    ) -> AsyncIterator[ChatChunk]:
        """
        流式聊天

        Args:
            request: 聊天请求
            user_id: 用户 ID

        Yields:
            ChatChunk 流式块
        """
        context = None
        try:
            logger.debug("ChatService.chat_stream 开始: message={}...", request.message[:30])

            start_time = time.time()

            # 解析系统提示词（支持 prompt_key 模板 + 时间注入）
            system_prompt = await self._resolve_system_prompt(request, user_id)

            # 获取或创建会话上下文
            conversation_id = request.conversation_id or str(uuid.uuid4())
            logger.debug("获取/创建会话上下文: {}", conversation_id)

            context = await self.context_manager.get_or_create(
                conversation_id=conversation_id,
                user_id=user_id,
                system_prompt=system_prompt,
            )

            # 添加用户消息
            context.add_user_message(request.message)

            # 构建消息
            messages = context.get_messages_for_api(
                max_tokens=ai_config.context.max_tokens
            )
            logger.debug("[chat_stream] API messages ({} 条): {}", len(messages), [{'role': m['role'], 'content': m['content'][:80] + '...' if len(m['content']) > 80 else m['content']} for m in messages])

            # 收集完整回复
            full_content = ""

            # 流式调用
            logger.debug("开始调用 provider.chat_completion_stream")
            async for chunk in self.provider.chat_completion_stream(
                messages=messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                full_content += chunk.content

                if chunk.is_final:
                    # 最后一块，添加元数据
                    elapsed_ms = int((time.time() - start_time) * 1000)

                    # 添加助手回复到上下文
                    context.add_assistant_message(full_content)
                    await self.context_manager.save(context)

                    yield ChatChunk(
                        content=chunk.content,
                        is_final=True,
                        conversation_id=conversation_id,
                        metadata=AIMetadata(
                            model=request.model or ai_config.openai.chat_model,
                            provider=self.provider.name,
                            latency_ms=elapsed_ms,
                            request_id=get_request_id(),
                        ),
                    )

                    logger.info(
                        "流式聊天完成: conversation={}, time={}ms",
                        conversation_id, elapsed_ms
                    )
                else:
                    yield ChatChunk(
                        content=chunk.content,
                        is_final=False,
                    )

        except Exception as e:
            logger.error("ChatService.chat_stream 异常: {}", e)
            # 发生错误时，移除刚添加的用户消息
            if context and context.messages and context.messages[-1].role == "user":
                context.messages.pop()
            raise

    async def get_history(
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
        context = await self.context_manager.get(conversation_id)

        if not context:
            return {
                "conversation_id": conversation_id,
                "messages": [],
                "total_tokens": 0,
                "exists": False,
            }

        return {
            "conversation_id": conversation_id,
            "messages": context.get_history(limit),
            "total_tokens": context.total_tokens,
            "message_count": len(context.messages),
            "exists": True,
        }

    async def clear_history(self, conversation_id: str) -> bool:
        """清空会话历史"""
        context = await self.context_manager.get(conversation_id)
        if context:
            context.clear()
            await self.context_manager.save(context)
            logger.info("会话历史已清空: {}", conversation_id)
            return True
        return False

    async def delete_conversation(self, conversation_id: str) -> bool:
        """删除会话"""
        return await self.context_manager.delete(conversation_id)
