"""AI 聊天端点

端点列表：
- POST /chat          - 普通聊天（支持提示词模板）
- POST /chat/stream   - 流式聊天 (SSE)
"""
from fastapi import APIRouter, Depends

from app.schemas.response import Response
from sse_starlette.sse import EventSourceResponse
import json

from app.api.deps import get_current_active_user
from app.core.exceptions import ServiceUnavailableError, InternalError
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.ai.facade import ai
from app.ai.schemas.chat import ChatRequest, ChatResponse
from app.ai.config import ai_config
from app.ai.exceptions import AIError
from app.core.logger import logger

router = APIRouter()


# ==================== 聊天端点 ====================

@router.post(
    "/chat",
    response_model=Response[ChatResponse],
    summary="AI 聊天",
    description="与 AI 进行对话，支持多轮会话和提示词模板"
)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_active_user),
    _: None = Depends(rate_limit(requests_per_minute=30)),  # AI 聊天限流
) -> ChatResponse:
    """
    AI 聊天

    - **message**: 用户消息
    - **conversation_id**: 会话 ID（可选，用于多轮对话）
    - **system_prompt**: 系统提示词（可选，优先级最高）
    - **prompt_key**: 提示词模板 key（可选，如 'chat/default', 'roles/business/customer_service'）
    - **prompt_variables**: 提示词变量（可选，如 {'company_name': 'ABC科技'}）
    - **temperature**: 采样温度 0-2（可选，默认 0.7）
    - **max_tokens**: 最大生成 token 数（可选）
    """
    if not ai_config.chat_enabled:
        raise ServiceUnavailableError("聊天功能未启用")

    try:
        response = await ai.chat(
            message=request.message,
            conversation_id=request.conversation_id,
            system_prompt=request.system_prompt,
            prompt_key=request.prompt_key,
            prompt_variables=request.prompt_variables,
            user_id=current_user.id,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return Response(data=response)
    except AIError as e:
        logger.error("AI 聊天失败: {}", e)
        raise InternalError(e.message) from e


@router.post(
    "/chat/stream",
    summary="AI 流式聊天",
    description="与 AI 进行流式对话，实时返回生成内容（SSE）",
    responses={
        200: {
            "description": "SSE 流式响应",
            "content": {
                "text/event-stream": {
                    "example": "event: message\ndata: {\"content\": \"你好\"}\n\nevent: done\ndata: {\"content\": \"\", \"is_final\": true, \"conversation_id\": \"...\"}"
                }
            }
        }
    }
)
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_active_user),
    _: None = Depends(rate_limit(requests_per_minute=20)),  # 流式聊天限流
):
    """
    AI 流式聊天（Server-Sent Events）

    返回 SSE 事件流，每个事件包含：
    - event: "message" | "done" | "error"
    - data: JSON 格式的 ChatChunk
    """
    if not ai_config.chat_enabled:
        raise ServiceUnavailableError("聊天功能未启用")

    async def event_generator():
        """生成 SSE 事件"""
        has_yielded = False
        try:
            logger.debug("开始流式聊天: message={}...", request.message[:50])

            async for chunk in ai.chat_stream(
                message=request.message,
                conversation_id=request.conversation_id,
                system_prompt=request.system_prompt,
                prompt_key=request.prompt_key,
                prompt_variables=request.prompt_variables,
                user_id=current_user.id,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                has_yielded = True
                if chunk.is_final:
                    yield {
                        "event": "done",
                        "data": json.dumps(chunk.model_dump(), ensure_ascii=False),
                    }
                else:
                    yield {
                        "event": "message",
                        "data": json.dumps({"content": chunk.content}, ensure_ascii=False),
                    }
        except AIError as e:
            logger.error("AI 流式聊天失败: {}", e)
            yield {
                "event": "error",
                "data": json.dumps({"error": e.message}, ensure_ascii=False),
            }
        except Exception as e:
            import traceback
            logger.error("AI 流式聊天异常: {}\n{}", e, traceback.format_exc())
            yield {
                "event": "error",
                "data": json.dumps({"error": f"服务器内部错误: {e!s}"}, ensure_ascii=False),
            }
        finally:
            # 确保至少 yield 一个事件（防止 ASGI callable returned without completing response）
            if not has_yielded:
                logger.warning("流式聊天未产生任何事件，发送错误事件")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": "流式响应异常终止"}, ensure_ascii=False),
                }

    return EventSourceResponse(event_generator())
