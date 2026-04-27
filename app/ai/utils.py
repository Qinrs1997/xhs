"""AI 通用工具函数

提供带重试、超时等增强功能的 AI 调用封装。
"""
import asyncio


from app.core.exceptions import InternalError

from app.core.logger import logger


async def ai_chat_with_retry(
    ai_facade,
    *,
    message: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = 2,
    timeout: int = 60,
):
    """带超时和重试的 AI 调用

    通用封装，可在任何需要可靠 AI 调用的场景使用。

    Args:
        ai_facade: AIFacade 实例
        message: 发送给 AI 的消息
        model: 模型名称（None 则使用默认）
        temperature: 温度参数
        max_tokens: 最大 token 数
        max_retries: 最大重试次数
        timeout: 单次调用超时（秒）

    Returns:
        AI 响应对象

    Raises:
        InternalError: 所有重试均失败
    """
    for attempt in range(max_retries + 1):
        try:
            kwargs = {
                "message": message,
                "temperature": temperature,
            }
            if model:
                kwargs["model"] = model
            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            return await asyncio.wait_for(
                ai_facade.chat(**kwargs),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.warning("AI 调用超时 (attempt {}/{})", attempt + 1, max_retries + 1)
            if attempt == max_retries:
                raise InternalError(f"AI 调用超时（已重试 {max_retries} 次）") from exc
        except Exception as e:  # noqa: BLE001
            logger.warning("AI 调用失败 (attempt {}): {}", attempt + 1, e)
            if attempt == max_retries:
                raise
            await asyncio.sleep(1 * (attempt + 1))  # 渐进退避
