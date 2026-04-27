"""AI 会话管理端点

端点列表：
- POST /conversations                    - 创建新会话
- GET  /conversations                    - 列出用户会话
- GET  /conversations/{id}               - 获取会话详情
- GET  /conversations/{id}/history       - 获取会话历史
- POST /conversations/{id}/clear         - 清空会话
- DELETE /conversations/{id}             - 删除会话
"""
from fastapi import APIRouter, Depends, Path

from app.api.deps import get_current_active_user
from app.core.exceptions import NotFoundError, InternalError
from app.models.user import User
from app.schemas.response import Response
from app.ai.facade import ai
from app.ai.schemas.chat import (
    ChatHistoryResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    ConversationDetailResponse,
)
from app.ai.schemas.common import Message
from app.ai.exceptions import AIError
from app.core.logger import logger

router = APIRouter()


# ==================== 会话管理端点 ====================

@router.get(
    "/conversations/{conversation_id}/history",
    response_model=Response[ChatHistoryResponse],
    summary="获取会话历史",
    description="获取指定会话的消息历史"
)
async def get_conversation_history(
    conversation_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
) -> ChatHistoryResponse:
    """
    获取会话历史

    - **conversation_id**: 会话 ID
    - **limit**: 返回消息数量限制（默认 50）
    """
    try:
        history = await ai.get_conversation_history(
            conversation_id=conversation_id,
            limit=limit,
        )

        # 安全处理空值
        if not history or not history.get("exists"):
            raise NotFoundError("会话不存在")

        return Response(data=ChatHistoryResponse(
            conversation_id=conversation_id,
            messages=[Message(**msg) for msg in history.get("messages", [])],
            total_tokens=history.get("total_tokens", 0),
        ))
    except NotFoundError:
        raise
    except AIError as e:
        raise InternalError(e.message) from e


@router.delete(
    "/conversations/{conversation_id}",
    response_model=Response[dict],
    summary="删除会话",
    description="删除指定会话及其历史记录"
)
async def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """删除会话"""
    success = await ai.delete_conversation(conversation_id)

    if not success:
        raise NotFoundError("会话不存在")

    return Response(data={"message": "会话已删除", "conversation_id": conversation_id})


@router.post(
    "/conversations/{conversation_id}/clear",
    response_model=Response[dict],
    summary="清空会话",
    description="清空会话历史但保留会话"
)
async def clear_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """清空会话历史"""
    success = await ai.clear_conversation(conversation_id)

    if not success:
        raise NotFoundError("会话不存在")

    return Response(data={"message": "会话历史已清空", "conversation_id": conversation_id})


@router.get(
    "/conversations",
    response_model=Response[dict],
    summary="列出用户会话",
    description="列出当前用户的所有会话"
)
async def list_conversations(
    limit: int = 20,
    current_user: User = Depends(get_current_active_user),
):
    """列出用户会话"""
    conversations = await ai.list_conversations(
        user_id=current_user.id,
        limit=limit,
    )

    return Response(data={
        "conversations": conversations,
        "total": len(conversations),
    })


@router.post(
    "/conversations",
    response_model=Response[CreateConversationResponse],
    summary="创建新会话",
    description="显式创建新会话，可指定提示词模板"
)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: User = Depends(get_current_active_user),
) -> CreateConversationResponse:
    """
    创建新会话

    - **prompt_key**: 提示词模板 key（可选）
    - **prompt_variables**: 模板变量（可选）
    - **system_prompt**: 自定义系统提示词（可选，优先级高于 prompt_key）
    - **title**: 会话标题（可选）
    - **metadata**: 自定义元数据（可选）

    返回新创建的会话 ID，后续聊天时传入该 ID 即可继续对话。
    """
    try:
        result = await ai.create_conversation(
            prompt_key=request.prompt_key,
            prompt_variables=request.prompt_variables,
            system_prompt=request.system_prompt,
            title=request.title,
            user_id=current_user.id,
            metadata=request.metadata,
        )
        return Response(data=CreateConversationResponse(**result))
    except AIError as e:
        logger.error("创建会话失败: {}", e)
        raise InternalError(e.message) from e


@router.get(
    "/conversations/{conversation_id}",
    response_model=Response[ConversationDetailResponse],
    summary="获取会话详情",
    description="获取指定会话的详细信息"
)
async def get_conversation_detail(
    conversation_id: str = Path(..., description="会话 ID"),
    current_user: User = Depends(get_current_active_user),
) -> ConversationDetailResponse:
    """
    获取会话详情

    返回会话的元数据、消息统计等信息。
    """
    try:
        detail = await ai.get_conversation_detail(conversation_id)

        if not detail:
            raise NotFoundError("会话不存在")

        return Response(data=ConversationDetailResponse(**detail))
    except NotFoundError:
        raise
    except AIError as e:
        raise InternalError(e.message) from e
