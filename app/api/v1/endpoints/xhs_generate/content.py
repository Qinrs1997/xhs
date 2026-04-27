"""XHS 文案生成接口

POST /content              —— 标准文案生成
POST /copywriting/generate —— 兼容路径（老前端使用）
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.xhs.content import XHSContentService
from app.ai.services.xhs.schemas import (
    CopywritingGenerateRequest,
    XHSContentRequest,
    XHSContentResponse,
)
from app.api.deps import get_current_active_user
from app.api.v1.endpoints.xhs_helpers import (
    deduct_xhs_credits,
    ensure_xhs_credits,
    get_xhs_credit_cost,
    require_xhs_enabled,
    save_copywriting_to_task,
)
from app.core.database import get_async_db
from app.core.exceptions import AppException, InternalError, ValidationError
from app.core.logger import logger
from app.models.user import User

router = APIRouter()
_content_service = XHSContentService()


def _wrap_content_error(e: Exception) -> None:
    """把生成错误映射到 ValidationError / InternalError"""
    if isinstance(e, AppException):
        raise e
    if isinstance(e, ValueError) and "AI 返回内容格式不正确" in str(e):
        raise ValidationError(str(e)) from e
    raise InternalError(str(e)) from e


@router.post(
    "/content",
    response_model=XHSContentResponse,
    dependencies=[Depends(require_xhs_enabled)],
)
async def generate_content(
    request: XHSContentRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """生成小红书文案（支持风格和自定义模型）"""
    try:
        credit_cost = get_xhs_credit_cost("content")
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        pages_data = request.pages if isinstance(request.pages, list) else None

        result = await _content_service.generate_content(
            topic=request.topic,
            outline=request.outline or "",
            pages=pages_data,
            style=request.style or "casual",
            model=request.model,
            user_id=current_user.id,
        )

        await save_copywriting_to_task(db, request.task_id, current_user.id, result)
        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_content",
            description="XHS copywriting generation",
            reference_id=str(request.task_id) if request.task_id else None,
        )
        await db.commit()
        return result
    except Exception as e:
        logger.exception("XHS 文案生成失败: {}", e)
        _wrap_content_error(e)


@router.post(
    "/copywriting/generate",
    response_model=XHSContentResponse,
    summary="AI 生成发布文案(兼容路径)",
    dependencies=[Depends(require_xhs_enabled)],
)
async def generate_copywriting_alias(
    request: CopywritingGenerateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """文案生成(兼容路径)"""
    try:
        credit_cost = get_xhs_credit_cost("content")
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        result = await _content_service.generate_content(
            topic=request.topic,
            pages=request.pages,
            style=request.style or "casual",
            copy_length=request.copy_length or "medium",
            tag_count=request.tag_count or 5,
            title_count=request.title_count or 3,
            include_emoji=request.include_emoji if request.include_emoji is not None else True,
            user_id=current_user.id,
        )

        await save_copywriting_to_task(db, request.task_id, current_user.id, result)
        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_content",
            description="XHS copywriting generation",
            reference_id=str(request.task_id) if request.task_id else None,
        )
        await db.commit()
        return result
    except Exception as e:
        logger.exception("XHS 文案生成失败: {}", e)
        _wrap_content_error(e)
