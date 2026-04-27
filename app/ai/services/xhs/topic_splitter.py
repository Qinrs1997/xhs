"""选题拆分服务

将搜索结果拆分为多个小红书写作角度。

使用方式：
    from app.ai.services.xhs.topic_splitter import topic_splitter_service

    angles = await topic_splitter_service.split_topics(
        topic="2024年最好用的防晒霜",
        search_results=search_results,
        count=7,
    )
"""
from __future__ import annotations

import asyncio
from typing import Optional

from app.ai.facade import ai
from app.ai.prompts import prompts
from app.ai.config import ai_config
from app.ai.services.xhs.utils import parse_json_response
from app.core.logger import logger

# 超时和重试配置
SPLIT_TIMEOUT = 90  # 拆分任务 prompt 较长，给更多时间
SPLIT_MAX_RETRIES = 2


class TopicSplitterService:
    """选题拆分服务：将搜索结果拆分为多个小红书写作角度"""

    async def split_topics(
        self,
        topic: str,
        search_results: list[dict],
        count: int = 7,
        model: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> list[dict]:
        """从搜索结果中拆分出多个写作角度

        Args:
            topic: 用户主题
            search_results: 搜索结果列表（必须由调用方提供）
            count: 拆分角度数量
            model: AI 模型名称

        Returns:
            角度列表，每个角度包含:
                - angle_title: 选题标题
                - key_points: 核心要点列表
                - source_urls: 引用来源 URL 列表
                - content_direction: 内容方向简述
        """
        if not ai_config.chat_enabled:
            raise ValueError("AI chat 功能未启用")

        if not search_results:
            raise ValueError("搜索结果为空，无法拆分选题")

        # 1. 将搜索结果格式化为文本
        search_text = self._format_search_results(search_results)

        # 2. 构建 prompt
        prompt = await prompts.get(
            "xhs/topic_split",
            {
                "topic": topic,
                "search_results": search_text,
                "count": count,
            },
            user_id=user_id,
        )
        if not prompt:
            raise ValueError("xhs/topic_split prompt 模板未找到")

        # 3. 调用 LLM
        chat_model = model or ai_config.openai.chat_model
        logger.info(
            "选题拆分: topic='{}', count={}, model={}, search_results={}条",
            topic, count, chat_model, len(search_results),
        )

        response = await self._chat_with_retry(
            message=prompt,
            model=chat_model,
            temperature=0.8,  # 略高温度，鼓励多样性
            max_tokens=ai_config.openai.default_max_tokens,
        )

        # 4. 解析 JSON 响应
        try:
            data = parse_json_response(response.content)
        except ValueError:
            logger.error("选题拆分 JSON 解析失败: {}", response.content[:500])
            raise ValueError("AI 返回的选题格式不正确，请重试") from None

        # 兼容 {angles: [...]} 和直接返回列表两种格式
        angles = data.get("angles", data.get("prompts", []))
        if isinstance(data, list):
            angles = data

        if not angles:
            raise ValueError("AI 未返回有效的选题角度")

        logger.info("选题拆分完成: topic='{}', 实际拆出 {} 个角度", topic, len(angles))

        return angles

    @staticmethod
    def _format_search_results(results: list[dict]) -> str:
        """将搜索结果格式化为 LLM 可读的文本"""
        parts = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            content = r.get("content", "")

            # 优先用 content，不够就用 snippet
            text = content or snippet
            if text and len(text) > 500:
                text = text[:500] + "..."

            parts.append(
                f"[{i}] {title}\n"
                f"链接: {url}\n"
                f"内容: {text}\n"
            )
        return "\n".join(parts)

    async def _chat_with_retry(self, **kwargs):
        """带超时重试的 AI 调用"""
        for attempt in range(SPLIT_MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    ai.chat(**kwargs),
                    timeout=SPLIT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "选题拆分超时 (attempt {}/{})",
                    attempt + 1, SPLIT_MAX_RETRIES + 1,
                )
                if attempt == SPLIT_MAX_RETRIES:
                    raise ValueError("AI 调用超时，请稍后重试") from None
            except Exception as e:
                logger.warning(
                    "选题拆分失败 (attempt {}): {}",
                    attempt + 1, e,
                )
                if attempt == SPLIT_MAX_RETRIES:
                    raise
                await asyncio.sleep(1 * (attempt + 1))


# 模块级单例
topic_splitter_service = TopicSplitterService()
