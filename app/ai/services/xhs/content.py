"""XHS 文案生成服务（增强版）

支持：
- 风格参数（casual/professional/humorous）
- pages 数组代替 outline 提供上下文
- 自定义 AI 模型
- 返回 emoji_title 备用标题
"""
from __future__ import annotations

import asyncio

from app.ai.facade import ai
from app.ai.prompts import prompts
from app.ai.config import ai_config
from app.ai.services.xhs.schemas import XHSContentResponse
from app.ai.services.xhs.utils import parse_json_response
from app.core.logger import logger

# 风格提示词映射
STYLE_PROMPTS = {
    "casual": "用轻松活泼、朋友聊天的语气，多用口语化表达、emoji、感叹词",
    "professional": "用专业、有深度的语气，注重数据和事实，少用口语化表达",
    "humorous": "用幽默搞笑的语气，善用比喻、夸张、段子，让人忍不住笑出声",
    "playful": "用俏皮可爱的语气，多用叠词、颜文字、可爱的表达方式",
    "literary": "用文艺清新的语气，善用比喻和意象，有诗意和美感",
}

# 文案长度提示
COPY_LENGTH_HINTS = {
    "short": "文案要简短精练，100-200字左右，突出核心卖点",
    "medium": "文案中等长度，300-500字，内容充实有丰富细节",
    "long": "文案要详尽丰富，600-1000字，深度分享和详细教程风格",
}

# AI 调用超时和重试配置
AI_TIMEOUT = 60
AI_MAX_RETRIES = 2


class XHSContentService:
    """生成小红书标题、文案和标签"""

    async def generate_content(
        self,
        topic: str,
        outline: str = "",
        pages: list | None = None,
        style: str = "casual",
        model: str | None = None,
        copy_length: str = "medium",
        tag_count: int = 5,
        title_count: int = 3,
        include_emoji: bool = True,
        user_id: int | None = None,
    ) -> XHSContentResponse:
        """生成文案"""
        if not ai_config.chat_enabled:
            raise ValueError("AI chat is disabled")

        # 如果传了 pages，拼接成 outline
        if pages and not outline:
            outline = self._pages_to_outline(pages)

        if not outline:
            outline = topic

        # 获取风格提示词
        style_hint = STYLE_PROMPTS.get(style, STYLE_PROMPTS["casual"])
        length_hint = COPY_LENGTH_HINTS.get(copy_length, COPY_LENGTH_HINTS["medium"])
        emoji_hint = "标题要包含合适的 emoji 表情" if include_emoji else "标题不要使用 emoji"

        # 构建 prompt(注入所有参数)
        prompt = await prompts.get(
            "xhs/content",
            {
                "topic": topic,
                "outline": outline,
                "style_hint": style_hint,
                "length_hint": length_hint,
                "tag_count": tag_count,
                "title_count": title_count,
                "emoji_hint": emoji_hint,
            },
            user_id=user_id,
        )
        if not prompt:
            raise ValueError("xhs/content prompt template not found")

        # 选择模型
        chat_model = model or ai_config.openai.chat_model

        logger.info("XHS 文案生成: style={}, model={}", style, chat_model)

        content_data = await self._chat_json_with_retry(
            prompt=prompt,
            model=chat_model,
            temperature=ai_config.openai.default_temperature,
            max_tokens=ai_config.openai.default_max_tokens,
        )

        titles, copywriting, tags, emoji_title = self._normalize_content_data(content_data)

        return XHSContentResponse(
            titles=titles,
            copywriting=copywriting,
            tags=tags,
            emoji_title=emoji_title,
        )

    def _normalize_content_data(self, content_data: dict):
        titles = content_data.get("titles", [])
        copywriting = content_data.get("copywriting", "")
        tags = content_data.get("tags", [])
        emoji_title = content_data.get("emoji_title", "")

        if isinstance(titles, str):
            titles = [titles]
        titles = [str(title).strip() for title in titles if str(title).strip()]

        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        else:
            tags = [str(tag).strip() for tag in tags if str(tag).strip()]

        if isinstance(copywriting, list):
            copywriting = "\n".join(str(item).strip() for item in copywriting if str(item).strip())
        copywriting = str(copywriting or "").strip()
        emoji_title = str(emoji_title or "").strip()

        if not titles or not copywriting:
            raise ValueError("AI 返回内容缺少标题或正文")

        # 如果 AI 没返回 emoji_title，从 titles 生成一个
        if not emoji_title:
            emoji_title = titles[0]

        return titles, copywriting, tags, emoji_title

    def _pages_to_outline(self, pages: list) -> str:
        """将 pages 数组转为大纲文本"""
        lines = []
        for page in pages:
            page_num = page.get("page_num", 0)
            page_type = page.get("type", "content")
            title = page.get("title", "")
            content = page.get("content", "")

            label = f"第{page_num}页"
            if page_type == "cover":
                label = "封面"
            elif page_type == "summary":
                label = "总结"

            if title:
                lines.append(f"【{label}】{title}")
            if content:
                lines.append(content)
            lines.append("")

        return "\n".join(lines).strip()

    async def _chat_json_with_retry(self, prompt: str, **kwargs):
        """调用 LLM 并解析 JSON；网络失败和格式失败都最多尝试 3 次。"""
        for attempt in range(AI_MAX_RETRIES + 1):
            attempt_prompt = prompt
            if attempt > 0:
                attempt_prompt = (
                    f"{prompt}\n\n"
                    "重要：上一次输出不是合法 JSON 或缺少 titles/copywriting 字段。"
                    "请只返回 JSON 对象，不要输出 Markdown 代码块或解释文字。"
                    "必须包含 titles 数组、copywriting 字符串、tags 数组、emoji_title 字符串。"
                )
            try:
                response = await asyncio.wait_for(
                    ai.chat(message=attempt_prompt, **kwargs),
                    timeout=AI_TIMEOUT,
                )
                content_data = parse_json_response(response.content)
                self._normalize_content_data(content_data)
                if attempt > 0:
                    logger.info(
                        "文案生成自动重试成功 (attempt {}/{})",
                        attempt + 1,
                        AI_MAX_RETRIES + 1,
                    )
                return content_data
            except asyncio.TimeoutError:
                logger.warning("文案生成超时 (attempt {}/{})", attempt + 1, AI_MAX_RETRIES + 1)
                if attempt == AI_MAX_RETRIES:
                    raise ValueError("AI 调用超时，请稍后重试") from None
            except ValueError as e:
                logger.warning("文案生成返回格式不合格 (attempt {}): {}", attempt + 1, e)
                if attempt == AI_MAX_RETRIES:
                    raise ValueError("AI 返回内容格式不正确，已自动重试 3 次，请稍后再试") from None
            except Exception as e:
                logger.warning("文案生成失败 (attempt {}): {}", attempt + 1, e)
                if attempt == AI_MAX_RETRIES:
                    raise
            await asyncio.sleep(1 * (attempt + 1))

        raise ValueError("AI 返回内容格式不正确，已自动重试 3 次，请稍后再试") from None

    async def _chat_with_retry(self, **kwargs):
        """带超时重试的 AI 调用"""
        for attempt in range(AI_MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    ai.chat(**kwargs),
                    timeout=AI_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("文案生成超时 (attempt {}/{})", attempt + 1, AI_MAX_RETRIES + 1)
                if attempt == AI_MAX_RETRIES:
                    raise ValueError("AI 调用超时，请稍后重试") from None
            except Exception as e:
                logger.warning("文案生成失败 (attempt {}): {}", attempt + 1, e)
                if attempt == AI_MAX_RETRIES:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
