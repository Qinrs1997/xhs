"""总结服务

提供内容总结相关的业务逻辑封装。

使用方式：
    from app.ai.services import SummaryService
    from app.ai.providers import get_provider

    service = SummaryService(provider=get_provider("openai"))

    response = await service.summarize_text("很长的文本...")
"""
import time
from typing import Optional

from app.ai.services.base import BaseAIService
from app.ai.providers.base import BaseProvider
from app.ai.core.context import ContextManager, get_context_manager
from app.ai.schemas.summary import SummaryRequest, SummaryResponse
from app.ai.schemas.common import AIMetadata, Usage
from app.ai.config import ai_config
from app.core.logger import logger
from app.core.context import get_request_id


class SummaryService(BaseAIService):
    """总结服务

    提供：
    - 文本总结
    - 会话总结
    - 多种总结风格
    """

    service_name = "summary"

    # 不同风格的提示词模板
    STYLE_PROMPTS = {
        "brief": (
            "请用简洁的语言总结以下内容，控制在 100 字以内：\n\n"
            "{text}"
        ),
        "detailed": (
            "请详细总结以下内容，包括主要观点和重要细节：\n\n"
            "{text}"
        ),
        "bullet": (
            "请将以下内容总结为要点列表，每个要点用 - 开头：\n\n"
            "{text}\n\n"
            "请按以下格式输出：\n"
            "- 要点1\n"
            "- 要点2\n"
            "..."
        ),
    }

    def __init__(
        self,
        provider: BaseProvider,
        context_manager: Optional[ContextManager] = None,
    ):
        super().__init__(provider, context_manager or get_context_manager())

    def _get_summary_prompt(
        self,
        text: str,
        style: str = "brief",
        max_length: Optional[int] = None,
    ) -> str:
        """构建总结提示词"""
        template = self.STYLE_PROMPTS.get(style, self.STYLE_PROMPTS["brief"])
        prompt = template.format(text=text)

        if max_length:
            prompt += f"\n\n请将总结控制在 {max_length} 字以内。"

        return prompt

    async def summarize_text(
        self,
        request: SummaryRequest,
    ) -> SummaryResponse:
        """
        文本总结

        Args:
            request: 总结请求

        Returns:
            SummaryResponse
        """
        if not request.text:
            raise ValueError("text 参数不能为空")

        start_time = time.time()
        original_length = len(request.text)

        # 构建提示词
        prompt = self._get_summary_prompt(
            text=request.text,
            style=request.style,
            max_length=request.max_length,
        )

        # 调用 Provider
        response = await self.provider.chat_completion(
            messages=[
                {"role": "system", "content": "你是一个专业的内容总结助手。"},
                {"role": "user", "content": prompt},
            ],
            model=ai_config.openai.summary_model,
            temperature=0.3,  # 总结任务使用较低温度
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        # 解析要点（如果是 bullet 风格）
        key_points = None
        if request.style == "bullet":
            key_points = [
                line.strip().lstrip("- ").strip()
                for line in response.content.split("\n")
                if line.strip().startswith("-")
            ]

        summary_length = len(response.content)
        compression_ratio = original_length / summary_length if summary_length > 0 else 0

        logger.info(
            "文本总结完成: style={}, 原文={}字, 总结={}字, 压缩比={:.1f}x, time={}ms",
            request.style, original_length, summary_length, compression_ratio, elapsed_ms
        )

        return SummaryResponse(
            summary=response.content,
            key_points=key_points,
            word_count=summary_length,
            compression_ratio=compression_ratio,
            metadata=AIMetadata(
                model=response.model,
                provider=self.provider.name,
                usage=Usage(**response.usage),
                latency_ms=elapsed_ms,
                request_id=get_request_id(),
            ),
        )

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
            SummaryResponse
        """
        # 获取会话上下文
        context = await self.context_manager.get(conversation_id)
        if not context or not context.messages:
            raise ValueError(f"会话不存在或为空: {conversation_id}")

        # 构建会话文本
        conversation_text = "\n".join([
            f"{msg.role}: {msg.content}"
            for msg in context.messages
        ])

        # 调用文本总结
        return await self.summarize_text(
            SummaryRequest(
                text=conversation_text,
                style=style,
            )
        )

    async def compress_context(
        self,
        conversation_id: str,
    ) -> str:
        """
        压缩会话上下文

        生成会话总结并替换历史消息。

        Args:
            conversation_id: 会话 ID

        Returns:
            生成的总结内容
        """
        context = await self.context_manager.get(conversation_id)
        if not context:
            raise ValueError(f"会话不存在: {conversation_id}")

        # 生成总结
        summary_response = await self.summarize_conversation(
            conversation_id=conversation_id,
            style="detailed",
        )

        # 压缩上下文
        context.compress_with_summary(summary_response.summary)
        await self.context_manager.save(context)

        logger.info("会话上下文已压缩: {}", conversation_id)

        return summary_response.summary
