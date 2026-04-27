"""XHS prompt endpoints."""

import json
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import prompts as prompt_manager
from app.ai.services.xhs.schemas import PromptOptimizeRequest, PromptsBatchRequest
from app.ai.services.xhs.utils import parse_json_response
from app.api.deps import get_current_active_user
from app.api.v1.endpoints.xhs_helpers import (
    ai_chat_with_retry,
    calculate_prompt_credit_cost,
    deduct_xhs_credits,
    ensure_xhs_credits,
    extract_tokens,
    get_xhs_credit_cost,
    get_task_if_provided,
    raise_xhs_error,
    require_xhs_enabled,
    save_task_safe,
    track_tokens,
)
from app.core.database import get_async_db
from app.core.logger import logger
from app.crud.xhs_task import xhs_task
from app.crud.xhs_template import xhs_template as xhs_template_crud
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()


def _normalize_prompt_item(item: Any, index: int) -> dict[str, Any]:
    """Normalize model output so the frontend can always bind image_prompt."""
    page_num = index + 1
    image_prompt = ""

    if isinstance(item, dict):
        raw_page_num = item.get("page_num", item.get("page", item.get("index")))
        try:
            page_num = int(raw_page_num)
            if page_num <= 0:
                page_num = index + 1
        except (TypeError, ValueError):
            page_num = index + 1

        image_prompt = (
            item.get("image_prompt")
            or item.get("prompt")
            or item.get("text")
            or item.get("content")
            or ""
        )
    else:
        image_prompt = str(item)

    return {
        "page_num": page_num,
        "image_prompt": str(image_prompt).strip(),
    }


def _merge_template_text(template_text: str, request_text: str) -> str:
    template_text = (template_text or "").strip()
    request_text = (request_text or "").strip()
    if not template_text:
        return request_text
    if not request_text:
        return template_text
    if template_text in request_text:
        return request_text
    if request_text in template_text:
        return template_text
    return f"{template_text}\n\n{request_text}"


async def _resolve_template_style(
    db: AsyncSession,
    request: PromptsBatchRequest,
) -> tuple[str, str]:
    style_prompt = request.style_prompt or ""
    negative_style_prompt = request.negative_style_prompt or ""
    if not request.template_id:
        return style_prompt, negative_style_prompt

    tpl = await xhs_template_crud.get_by_id(db, template_id=request.template_id)
    if tpl is None:
        logger.warning("Prompts template fallback skipped: template_id={} not found", request.template_id)
        return style_prompt, negative_style_prompt

    style_prompt = _merge_template_text(tpl.style_prompt or "", style_prompt)
    negative_style_prompt = _merge_template_text(
        getattr(tpl, "negative_style_prompt", "") or "",
        negative_style_prompt,
    )
    return style_prompt, negative_style_prompt


@router.post(
    "/prompts",
    response_model=Response[dict],
    summary="Batch generate image prompts",
    dependencies=[Depends(require_xhs_enabled)],
)
async def generate_prompts_batch(
    request: PromptsBatchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Batch generate image prompts for XHS pages."""

    try:
        credit_cost = calculate_prompt_credit_cost(len(request.pages))
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        style_prompt, negative_style_prompt = await _resolve_template_style(db, request)
        logger.info(
            "/xhs/prompts received: user={}, task_id={}, pages={}, template_id={}, "
            "style_prompt_len={}, negative_style_prompt_len={}",
            current_user.id,
            request.task_id,
            len(request.pages),
            request.template_id,
            len(style_prompt or ""),
            len(negative_style_prompt or ""),
        )

        pages_json = json.dumps(request.pages, ensure_ascii=False, indent=2)
        prompt = await prompt_manager.get(
            "xhs/prompts_batch",
            {
                "topic": request.topic,
                "style_prompt": style_prompt or "",
                "negative_style_prompt": negative_style_prompt or "",
                "pages_json": pages_json,
            },
            user_id=current_user.id,
        )
        if not prompt:
            raise ValueError("prompts_batch template not found")

        response = await ai_chat_with_retry(message=prompt, temperature=0.7)
        ai_tokens = extract_tokens(response)
        result = parse_json_response(response.content)

        prompts_list = result.get("prompts", [])
        normalized_prompts = [
            _normalize_prompt_item(item, index)
            for index, item in enumerate(prompts_list)
        ]
        if request.task_id and normalized_prompts:
            task = await get_task_if_provided(db, request.task_id, current_user.id)
            if task:
                try:
                    prompt_values = [p["image_prompt"] for p in normalized_prompts]
                    await xhs_task.update_pages_batch(
                        db,
                        task=task,
                        field_name="image_prompt",
                        values=prompt_values,
                    )
                    await track_tokens(db, task, ai_tokens, "batch_prompts")
                    await save_task_safe(db, "batch_prompts")
                except Exception as save_err:
                    logger.warning(
                        "Failed to persist generated prompts to task: {}",
                        save_err,
                    )

        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_prompts",
            description="XHS image prompt generation",
            reference_id=str(request.task_id) if request.task_id else None,
        )
        await db.commit()

        return Response(
            code=200,
            success=True,
            message="Image prompts generated successfully",
            data={"prompts": normalized_prompts},
        )
    except Exception as exc:
        logger.exception("Batch prompt generation failed: {}", exc)
        raise_xhs_error(exc, "batch prompt generation")


@router.post(
    "/prompt/optimize",
    response_model=Response[dict],
    summary="Optimize a single image prompt",
    dependencies=[Depends(require_xhs_enabled)],
)
async def optimize_prompt(
    request: PromptOptimizeRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Optimize a single image prompt."""

    try:
        credit_cost = get_xhs_credit_cost("prompt_optimize")
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        prompt = await prompt_manager.get(
            "xhs/prompt_optimize",
            {
                "original_prompt": request.prompt,
                "page_content": request.page_content or "",
                "page_type": request.page_type or "",
            },
            user_id=current_user.id,
        )
        if not prompt:
            raise ValueError("prompt_optimize template not found")

        response = await ai_chat_with_retry(
            message=prompt,
            temperature=0.7,
            max_tokens=1000,
        )
        ai_tokens = extract_tokens(response)
        optimized = response.content.strip()

        if request.task_id and request.page_index is not None:
            task = await get_task_if_provided(db, request.task_id, current_user.id)
            if task:
                try:
                    await xhs_task.update_page_field(
                        db,
                        task=task,
                        page_index=request.page_index,
                        updates={"image_prompt": optimized},
                    )
                    await track_tokens(db, task, ai_tokens, "optimize_prompt")
                    await save_task_safe(db, "optimize_prompt")
                except Exception as save_err:
                    logger.warning(
                        "Failed to persist optimized prompt to task: {}",
                        save_err,
                    )

        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_prompt_optimize",
            description="XHS prompt optimization",
            reference_id=(
                f"{request.task_id}:{request.page_index}"
                if request.task_id is not None and request.page_index is not None
                else str(request.task_id) if request.task_id is not None else None
            ),
        )
        await db.commit()

        return Response(
            code=200,
            success=True,
            message="Prompt optimized successfully",
            data={"optimized_prompt": optimized},
        )
    except Exception as exc:
        logger.exception("Prompt optimization failed: {}", exc)
        raise_xhs_error(exc, "prompt optimization")
