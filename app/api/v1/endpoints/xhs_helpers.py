"""Shared helpers for XHS endpoints."""

from __future__ import annotations

import asyncio
from math import ceil
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import ai_config
from app.ai.facade import ai
from app.ai.utils import ai_chat_with_retry as _ai_chat_with_retry
from app.core.exceptions import (
    AppException,
    ExternalServiceError,
    InternalError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.logger import logger
from app.crud.xhs_task import xhs_task


async def require_xhs_enabled() -> None:
    """Ensure the XHS feature is enabled."""
    if not ai_config.xhs_enabled:
        raise ServiceUnavailableError("小红书功能未启用")


async def require_image_enabled() -> None:
    """Allow image generation when either static or DB image config exists."""
    if not ai_config.xhs_enabled:
        raise ServiceUnavailableError("小红书功能未启用")

    if ai_config.image_enabled:
        return

    from app.ai.services.dynamic_config import get_dynamic_config

    dyn_config = await get_dynamic_config(service_type="image")
    if not dyn_config.base_url or not dyn_config.api_key:
        raise ServiceUnavailableError("图片生成功能未启用")


def raise_xhs_error(error: Exception, context: str = "XHS 操作") -> None:
    """Map internal exceptions to the API error types used by the project."""
    import httpx

    from app.ai.exceptions import AIError

    if isinstance(error, AppException):
        raise error

    if isinstance(error, ValueError):
        raise ValidationError(str(error))

    if isinstance(error, asyncio.TimeoutError):
        raise ExternalServiceError(f"{context}超时，请稍后重试")

    if isinstance(error, httpx.TimeoutException):
        raise ExternalServiceError(f"{context}网络超时")

    if isinstance(error, AIError):
        raise ServiceUnavailableError(f"AI 服务异常: {error}")

    raise InternalError(str(error))


async def ai_chat_with_retry(
    message: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = 2,
    timeout: int = 60,
):
    """Run an AI chat request with shared defaults and retry behavior."""
    chat_model = model or ai_config.openai.chat_model
    chat_max_tokens = max_tokens or ai_config.openai.default_max_tokens
    return await _ai_chat_with_retry(
        ai,
        message=message,
        model=chat_model,
        temperature=temperature,
        max_tokens=chat_max_tokens,
        max_retries=max_retries,
        timeout=timeout,
    )


async def get_task_if_provided(
    db: AsyncSession, task_id: Optional[int], user_id: int
):
    """Safely load a user task when ``task_id`` is present."""
    if not task_id:
        return None

    try:
        return await xhs_task.get_user_task(db, task_id=task_id, user_id=user_id)
    except Exception as exc:
        logger.warning("Failed to load task {}: {}", task_id, exc)
        return None


async def save_task_safe(db: AsyncSession, context: str = "") -> None:
    """Commit task changes and swallow the error after logging."""
    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to save {} task changes: {}", context, exc)
        await db.rollback()


def extract_tokens(response) -> int:
    """Extract ``total_tokens`` from a few known response shapes."""
    try:
        if hasattr(response, "metadata") and response.metadata:
            usage = response.metadata.usage
            if usage:
                return usage.total_tokens or 0
        if hasattr(response, "usage") and isinstance(response.usage, dict):
            return response.usage.get("total_tokens", 0)
    except Exception as exc:
        logger.debug("Token extraction fallback triggered: {}", exc)
    return 0


async def track_tokens(
    db: AsyncSession, task, tokens: int, context: str = ""
) -> None:
    """Accumulate token usage for an XHS task."""
    if not task or tokens <= 0:
        return

    try:
        await xhs_task.add_tokens(db, task=task, tokens=tokens)
        logger.info("Token usage tracked: {} +{} tokens (task={})", context, tokens, task.id)
    except Exception as exc:
        logger.warning("Failed to track tokens: {}", exc)


async def update_task_status(db: AsyncSession, task, status: str) -> None:
    """Safely update task status."""
    if not task:
        return

    try:
        from app.core.timezone import now_utc
        from app.models.xhs_task import TaskStatus

        task.status = TaskStatus(status)
        if status == "completed":
            task.completed_at = now_utc()
        await db.flush()
    except Exception as exc:
        logger.warning("Failed to update task status: {}", exc)


def get_xhs_credit_cost(operation: str) -> int:
    """Return the configured credit cost for an XHS operation."""
    from app.services.credit_service import get_credit_costs

    return int(get_credit_costs().get(operation, 0) or 0)


def resolve_grid_capacity(grid_config: dict | None = None) -> int:
    """Resolve batch-grid capacity from request config, defaulting to 2x2."""
    grid_config = grid_config or {}
    try:
        rows = int(grid_config.get("rows") or 2)
        cols = int(grid_config.get("cols") or 2)
    except (TypeError, ValueError):
        rows, cols = 2, 2
    return max(rows * cols, 1)


def calculate_image_credit_cost(
    generation_mode: str | None,
    page_count: int,
    *,
    grid_config: dict | None = None,
    image_quality: str | None = None,
    images_per_page: int | None = 1,
    api_calls: int | None = None,
) -> int:
    """Calculate the image-generation credit cost from API-call count."""
    if page_count <= 0:
        return 0

    per_call_cost = get_xhs_credit_cost(
        "image_hd" if (image_quality or "").lower() == "hd" else "image_standard"
    )
    if per_call_cost <= 0:
        return 0

    if api_calls is None:
        if generation_mode == "batch_grid":
            grid_capacity = resolve_grid_capacity(grid_config)
            try:
                max_pages_per_grid = int(ai_config.image.batch_grid.max_pages_per_grid)
            except (TypeError, ValueError):
                max_pages_per_grid = grid_capacity
            pages_per_call = max(min(grid_capacity, max_pages_per_grid), 1)
            api_calls = ceil(page_count / pages_per_call)
        else:
            try:
                multiplier = int(images_per_page or 1)
            except (TypeError, ValueError):
                multiplier = 1
            multiplier = max(multiplier, 1)
            api_calls = page_count * multiplier

    return max(int(api_calls or 0), 0) * per_call_cost


def calculate_prompt_credit_cost(page_count: int) -> int:
    """Charge prompt generation per page, matching the frontend estimate."""
    return max(page_count, 0) * get_xhs_credit_cost("prompts_batch")


async def ensure_xhs_credits(db: AsyncSession, user_id: int, cost: int) -> None:
    """Fail fast when a user does not have enough credits."""
    if cost <= 0:
        return

    from app.services.credit_service import credit_service

    await credit_service.check_balance(db, user_id, cost)


async def deduct_xhs_credits(
    db: AsyncSession,
    user_id: int,
    cost: int,
    *,
    transaction_type: str,
    description: str,
    reference_id: str | None = None,
) -> None:
    """Create a credit deduction transaction. Caller owns commit/rollback."""
    if cost <= 0:
        return

    from app.services.credit_service import credit_service

    await credit_service.deduct(
        db,
        user_id,
        amount=cost,
        type=transaction_type,
        description=description,
        reference_id=reference_id,
    )


async def save_copywriting_to_task(
    db: AsyncSession, task_id: Optional[int], user_id: int, result
) -> None:
    """Persist generated copywriting into the task record."""
    if not task_id:
        return

    task = await get_task_if_provided(db, task_id, user_id)
    if not task:
        return

    try:
        copywriting_data = {
            "titles": result.titles,
            "copywriting": result.copywriting,
            "tags": result.tags,
            "emoji_title": result.emoji_title,
        }
        await xhs_task.update_copywriting(db, task=task, copywriting=copywriting_data)
        await save_task_safe(db, "copywriting")
    except Exception as exc:
        logger.warning("Failed to save copywriting to task: {}", exc)
