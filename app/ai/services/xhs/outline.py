"""XHS outline generation service."""
from __future__ import annotations

import asyncio
from typing import List, Optional

from app.ai.facade import ai
from app.ai.prompts import prompts
from app.ai.config import ai_config
from app.ai.services.xhs.schemas import XHSOutlineResponse
from app.ai.services.xhs.utils import parse_outline
from app.core.logger import logger

# AI 调用超时和重试配置
AI_TIMEOUT = 60
AI_MAX_RETRIES = 2


class XHSOutlineService:
    """Generate XHS outline and parse pages."""

    async def generate_outline(
        self,
        topic: str,
        images: Optional[List[str]] = None,
        style_prompt: Optional[str] = None,
        page_count: Optional[int] = None,
        tone: Optional[str] = None,
        language: Optional[str] = None,
        user_id: Optional[int] = None,
        content_prompt: Optional[str] = None,
        search_context: Optional[str] = None,
    ) -> XHSOutlineResponse:
        if not ai_config.chat_enabled:
            raise ValueError("AI chat is disabled")

        tone_hints = {
            "casual": "轻松活泼、朋友聊天",
            "professional": "专业深度",
            "playful": "俏皮可爱",
            "literary": "文艺清新",
        }
        lang_map = {"en": "English", "ja": "日语", "ko": "韩语", "zh": "中文"}

        prompt = await prompts.get(
            "xhs/outline",
            {
                "topic": topic,
                "tone": tone_hints.get(tone, tone) if tone else "",
                "language": lang_map.get(language, language) if language and language != "zh" else "",
            },
            user_id=user_id,
        )
        if not prompt:
            raise ValueError("xhs/outline prompt template not found")

        if style_prompt:
            prompt += f"\n\n风格要求：{style_prompt}"

        if content_prompt:
            prompt += f"\n\n正文结构要求：\n{content_prompt}"

        if search_context:
            prompt += f"\n\n参考资料（来自实时搜索）：\n{search_context}"

        if page_count and page_count > 0:
            prompt += f"\n\n请生成 {page_count} 页内容（含封面和总结页）。"

        if images:
            prompt += (
                "\n\n注意：用户提供了 %d 张参考图片，请考虑图片内容和风格。"
                % len(images)
            )

        logger.info("XHS outline prompt prepared")

        last_error: Exception | None = None
        for attempt in range(AI_MAX_RETRIES + 1):
            attempt_prompt = prompt
            if attempt > 0:
                attempt_prompt = (
                    f"{prompt}\n\n"
                    "重要：上一次输出无法解析或没有生成有效页面。"
                    "请严格按小红书图文大纲格式输出，每页用 <page> 分隔，"
                    "每页包含页面类型、标题和正文内容，不要输出解释说明。"
                )
            try:
                response = await asyncio.wait_for(
                    ai.chat(
                        message=attempt_prompt,
                        model=ai_config.openai.chat_model,
                        temperature=ai_config.openai.default_temperature,
                        max_tokens=ai_config.openai.default_max_tokens,
                    ),
                    timeout=AI_TIMEOUT,
                )
                outline_text = response.content
                pages = parse_outline(outline_text)
                if not pages:
                    raise ValueError("AI 未返回可解析的大纲页面")
                if attempt > 0:
                    logger.info(
                        "大纲生成自动重试成功 (attempt {}/{})",
                        attempt + 1,
                        AI_MAX_RETRIES + 1,
                    )
                return XHSOutlineResponse(outline=outline_text, pages=pages)
            except asyncio.TimeoutError:
                logger.warning("大纲生成超时 (attempt {}/{})", attempt + 1, AI_MAX_RETRIES + 1)
                if attempt == AI_MAX_RETRIES:
                    raise ValueError("AI 调用超时，请稍后重试") from None
                await asyncio.sleep(1 * (attempt + 1))
            except Exception as e:
                last_error = e
                logger.warning("大纲生成失败 (attempt {}): {}", attempt + 1, e)
                if attempt == AI_MAX_RETRIES:
                    if isinstance(e, ValueError):
                        raise ValueError("AI 返回大纲格式不正确，已自动重试 3 次，请稍后再试") from None
                    raise
                await asyncio.sleep(1 * (attempt + 1))

        raise ValueError(f"大纲生成失败: {last_error}") from None
