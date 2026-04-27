"""XHS image generation endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.ai.services.xhs.image import XHSImageService
from app.ai.services.xhs.schemas import (
    BatchGridRegenerateRequest,
    ImageRegenerateRequest,
    XHSImageStreamRequest,
)
from app.api.deps import get_current_active_user
from app.api.v1.endpoints.xhs_helpers import (
    calculate_image_credit_cost,
    deduct_xhs_credits,
    ensure_xhs_credits,
    get_xhs_credit_cost,
    get_task_if_provided,
    raise_xhs_error,
    require_image_enabled,
    save_task_safe,
    update_task_status,
)
from app.core.database import AsyncSessionLocal, get_async_db
from app.core.logger import logger
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()
_image_service = XHSImageService()
_background_image_tasks: set[asyncio.Task] = set()


def _merge_page_extra(task_pages: list | None, page_index: int, **updates: Any) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if task_pages and 0 <= page_index < len(task_pages):
        page = task_pages[page_index]
        if isinstance(page, dict) and isinstance(page.get("extra"), dict):
            extra = dict(page["extra"])

    for key, value in updates.items():
        if value is None:
            extra.pop(key, None)
        else:
            extra[key] = value
    return extra


def _image_updates_from_event(task_pages: list | None, event: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = event.get("data") or {}
    page_index = int(data.get("index", 0) or 0)
    event_type = event.get("event")

    if event_type == "page_start":
        return page_index, {
            "extra": _merge_page_extra(task_pages, page_index, status="running", error=None)
        }

    if event_type in {"page_done", "page_updated"}:
        original_url = data.get("original_url") or data.get("image_url") or data.get("url") or ""
        thumbnail_url = data.get("thumbnail_url") or data.get("url") or original_url
        return page_index, {
            "image_url": data.get("image_url") or data.get("url") or original_url,
            "thumbnail_url": thumbnail_url,
            "original_url": original_url,
            "extra": _merge_page_extra(task_pages, page_index, status="success", error=None),
        }

    if event_type == "page_error":
        return page_index, {
            "extra": _merge_page_extra(
                task_pages,
                page_index,
                status="failed",
                error=data.get("error") or data.get("message") or "image generation failed",
            )
        }

    return page_index, {}


@router.post("/image/stream", dependencies=[Depends(require_image_enabled)])
async def generate_image_stream(
    request: XHSImageStreamRequest,
    raw_request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """Stream XHS image generation progress via SSE."""
    db_task = None
    if request.task_id:
        db_task = await get_task_if_provided(db, request.task_id, current_user.id)

    # P2-A7j: 入口日志打印收到的关键字段,便于排查"前端传的是什么模式"
    logger.info(
        "/xhs/image/stream received: user={}, task_id={}, pages={}, "
        "generation_mode={}, grid_config={}, style_prompt_len={}, "
        "negative_style_prompt_len={}, image_engine={}",
        current_user.id,
        request.task_id,
        len(request.pages),
        request.generation_mode,
        request.grid_config,
        len(request.style_prompt or ""),
        len(request.negative_style_prompt or ""),
        request.image_engine,
    )

    planned_credit_cost = calculate_image_credit_cost(
        request.generation_mode,
        len(request.pages),
        grid_config=request.grid_config,
        image_quality=request.image_quality,
        images_per_page=request.images_per_page or 1,
    )
    await ensure_xhs_credits(db, current_user.id, planned_credit_cost)

    if db_task:
        try:
            await update_task_status(db, db_task, "generating")
            await db.commit()
        except Exception as exc:
            logger.warning("Failed to mark XHS task generating: {}", exc)

    async def _legacy_event_generator():
        nonlocal db_task

        # 按 generation_mode 分发:
        # - per_page: 原有逐页并发生图,每页 1 次 API (质量最佳)
        # - batch_grid: 一次 API 出 N*M 网格合成图 + 后端 Pillow 切割 (省钱 ~4x)
        #               降级时会自动 fallback 到 per_page 并推 mode_fallback 事件
        grid_cfg = request.grid_config or {}
        if request.generation_mode == "batch_grid":
            iterator = _image_service.generate_images_batch_grid(
                pages=request.pages,
                outline=request.outline,
                user_topic=request.user_topic,
                rows=grid_cfg.get("rows"),
                cols=grid_cfg.get("cols"),
                cell_size=grid_cfg.get("cell_size"),
                gap_px=grid_cfg.get("gap_px"),
                split_upscale_enabled=grid_cfg.get("split_upscale_enabled"),
                split_target_cell_size=grid_cfg.get("split_target_cell_size"),
                image_engine=request.image_engine,
                image_quality=request.image_quality,
                image_style=request.image_style,
                negative_prompt=request.negative_prompt,
                extra_params=request.extra_params,
                style_prompt=request.style_prompt,
                negative_style_prompt=request.negative_style_prompt,
                user_id=current_user.id,
            )
        else:
            iterator = _image_service.generate_images_stream(
                pages=request.pages,
                outline=request.outline,
                user_topic=request.user_topic,
                images=request.images,
                image_size=request.image_size,
                image_quality=request.image_quality,
                image_style=request.image_style,
                image_engine=request.image_engine,
                negative_prompt=request.negative_prompt,
                extra_params=request.extra_params,
                images_per_page=request.images_per_page or 1,
                user_id=current_user.id,
                style_prompt=request.style_prompt,
                negative_style_prompt=request.negative_style_prompt,
            )

        try:
            async for event in iterator:
                if await raw_request.is_disconnected():
                    logger.info("XHS image SSE client disconnected")
                    yield {
                        "event": "done",
                        "data": json.dumps(
                            {"message": "客户端已断开"},
                            ensure_ascii=False,
                        ),
                    }
                    return

                if db_task and event["event"] in {"page_done", "page_updated"}:
                    try:
                        await db.refresh(db_task)
                        page_index = event["data"].get("index", 0)
                        updates = {
                            "image_url": event["data"].get("url", ""),
                            "thumbnail_url": event["data"].get("thumbnail_url", ""),
                            "original_url": event["data"].get("original_url", ""),
                        }
                        await xhs_task.update_page_field(
                            db,
                            task=db_task,
                            page_index=page_index,
                            updates=updates,
                        )
                        await db.commit()
                    except Exception as exc:
                        logger.warning(
                            "Failed to persist XHS image result for page {}: {}",
                            event["data"].get("index"),
                            exc,
                        )

                if db_task and event["event"] == "done":
                    try:
                        await db.refresh(db_task)
                        success = event["data"].get("success", 0)
                        failed = event["data"].get("failed", 0)
                        if failed == 0 and success > 0:
                            await update_task_status(db, db_task, "completed")
                        elif success == 0 and failed > 0:
                            await update_task_status(db, db_task, "failed")
                        await db.commit()
                    except Exception as exc:
                        logger.warning("Failed to update XHS task status: {}", exc)

                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
        except asyncio.CancelledError:
            logger.info("XHS image SSE cancelled")
        except Exception as exc:
            logger.exception("Unexpected XHS image SSE error: {}", exc)
            if db_task:
                try:
                    await db.refresh(db_task)
                    await update_task_status(db, db_task, "failed")
                    db_task.error_message = str(exc)[:500]
                    await db.commit()
                except Exception as save_exc:
                    logger.warning(
                        "Failed to persist XHS image SSE error state: {}",
                        save_exc,
                    )
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)}, ensure_ascii=False),
            }

    user_id = current_user.id
    task_id = request.task_id
    actual_generation_mode = {"value": request.generation_mode or "per_page"}
    billing_charged = {"value": False}

    def build_iterator():
        grid_cfg = request.grid_config or {}
        if request.generation_mode == "batch_grid":
            return _image_service.generate_images_batch_grid(
                pages=request.pages,
                outline=request.outline,
                user_topic=request.user_topic,
                rows=grid_cfg.get("rows"),
                cols=grid_cfg.get("cols"),
                cell_size=grid_cfg.get("cell_size"),
                gap_px=grid_cfg.get("gap_px"),
                split_upscale_enabled=grid_cfg.get("split_upscale_enabled"),
                split_target_cell_size=grid_cfg.get("split_target_cell_size"),
                image_engine=request.image_engine,
                image_quality=request.image_quality,
                image_style=request.image_style,
                negative_prompt=request.negative_prompt,
                extra_params=request.extra_params,
                style_prompt=request.style_prompt,
                negative_style_prompt=request.negative_style_prompt,
                user_id=user_id,
            )

        return _image_service.generate_images_stream(
            pages=request.pages,
            outline=request.outline,
            user_topic=request.user_topic,
            images=request.images,
            image_size=request.image_size,
            image_quality=request.image_quality,
            image_style=request.image_style,
            image_engine=request.image_engine,
            negative_prompt=request.negative_prompt,
            extra_params=request.extra_params,
            images_per_page=request.images_per_page or 1,
            user_id=user_id,
            style_prompt=request.style_prompt,
            negative_style_prompt=request.negative_style_prompt,
        )

    async def persist_stream_event(event: dict[str, Any]) -> None:
        event_type = event.get("event")
        data = event.get("data") or {}

        if event_type == "mode_fallback":
            actual_generation_mode["value"] = data.get("to") or "per_page"
            return

        async with AsyncSessionLocal() as bg_db:
            task = None
            if task_id:
                task = await xhs_task.get_user_task(
                    bg_db,
                    task_id=task_id,
                    user_id=user_id,
                )

            if event_type in {"page_start", "page_done", "page_updated", "page_error"}:
                if not task:
                    return
                page_index, updates = _image_updates_from_event(task.pages or [], event)
                if not updates:
                    return
                await xhs_task.update_page_field(
                    bg_db,
                    task=task,
                    page_index=page_index,
                    updates=updates,
                )
                await bg_db.commit()
                return

            if event_type == "done":
                success = int(data.get("success", 0) or 0)
                failed = int(data.get("failed", 0) or 0)
                if task:
                    if failed == 0 and success > 0:
                        await update_task_status(bg_db, task, "completed")
                    elif failed > 0:
                        await update_task_status(bg_db, task, "failed")

                if success > 0 and not billing_charged["value"]:
                    billed_mode = data.get("mode") or actual_generation_mode["value"]
                    api_calls = data.get("api_calls")
                    credit_cost = calculate_image_credit_cost(
                        billed_mode,
                        success,
                        grid_config=request.grid_config,
                        image_quality=request.image_quality,
                        images_per_page=request.images_per_page or 1,
                        api_calls=int(api_calls) if api_calls is not None else None,
                    )
                    await deduct_xhs_credits(
                        bg_db,
                        user_id,
                        credit_cost,
                        transaction_type="usage_image",
                        description="XHS image generation",
                        reference_id=str(task_id) if task_id else data.get("task_id"),
                    )
                    billing_charged["value"] = True

                await bg_db.commit()

    async def persist_stream_failure(exc: Exception) -> None:
        if not task_id:
            return

        try:
            async with AsyncSessionLocal() as bg_db:
                task = await xhs_task.get_user_task(
                    bg_db,
                    task_id=task_id,
                    user_id=user_id,
                )
                if not task:
                    return
                await update_task_status(bg_db, task, "failed")
                task.error_message = str(exc)[:500]
                await bg_db.commit()
        except Exception as save_exc:
            logger.warning("Failed to persist XHS image error state: {}", save_exc)

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def run_generation_in_background() -> None:
        try:
            async for event in build_iterator():
                if event.get("event") == "mode_fallback":
                    try:
                        await persist_stream_event(event)
                        fallback_credit_cost = calculate_image_credit_cost(
                            "per_page",
                            len(request.pages),
                            image_quality=request.image_quality,
                            images_per_page=request.images_per_page or 1,
                        )
                        async with AsyncSessionLocal() as bg_db:
                            await ensure_xhs_credits(
                                bg_db,
                                user_id,
                                fallback_credit_cost,
                            )
                    except Exception as exc:
                        logger.warning("XHS image fallback blocked by credit check: {}", exc)
                        await event_queue.put(event)
                        await persist_stream_failure(exc)
                        await event_queue.put(
                            {"event": "error", "data": {"message": str(exc)}}
                        )
                        return
                    await event_queue.put(event)
                    continue

                try:
                    await persist_stream_event(event)
                except Exception as exc:
                    logger.warning(
                        "Failed to persist XHS image stream event {}: {}",
                        event.get("event"),
                        exc,
                    )
                    if event.get("event") == "done":
                        await persist_stream_failure(exc)
                        await event_queue.put(
                            {"event": "error", "data": {"message": str(exc)}}
                        )
                        return
                await event_queue.put(event)
        except Exception as exc:
            logger.exception("Unexpected XHS image background error: {}", exc)
            await persist_stream_failure(exc)
            await event_queue.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            await event_queue.put(None)

    runner = asyncio.create_task(run_generation_in_background())
    _background_image_tasks.add(runner)
    runner.add_done_callback(_background_image_tasks.discard)

    async def event_generator():
        try:
            while True:
                if await raw_request.is_disconnected():
                    logger.info(
                        "XHS image SSE client disconnected; task continues in background: task_id={}",
                        task_id,
                    )
                    return

                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    continue

                if event is None:
                    return

                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
        except asyncio.CancelledError:
            logger.info(
                "XHS image SSE cancelled; task continues in background: task_id={}",
                task_id,
            )

    return EventSourceResponse(event_generator())


@router.post(
    "/image/regenerate",
    response_model=Response[dict],
    summary="单页重新生成图片",
    dependencies=[Depends(require_image_enabled)],
)
async def regenerate_image(
    request: ImageRegenerateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Regenerate one XHS page image."""
    try:
        credit_cost = get_xhs_credit_cost("image_regenerate")
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        result_data = await _image_service.regenerate_single_page(
            page=request.page,
            outline=request.outline,
            user_topic=request.user_topic,
            images=request.images,
            image_size=request.image_size,
            image_quality=request.image_quality,
            image_style=request.image_style,
            image_engine=request.image_engine,
            negative_prompt=request.negative_prompt,
            extra_params=request.extra_params,
            user_id=current_user.id,
            style_prompt=request.style_prompt,
            negative_style_prompt=request.negative_style_prompt,
        )

        if request.task_id and request.page_index is not None:
            task = await get_task_if_provided(db, request.task_id, current_user.id)
            if task:
                try:
                    await xhs_task.update_page_field(
                        db,
                        task=task,
                        page_index=request.page_index,
                        updates={
                            "image_url": result_data.get("original_url", ""),
                            "thumbnail_url": result_data.get("thumbnail_url", ""),
                            "original_url": result_data.get("original_url", ""),
                        },
                    )
                    await save_task_safe(db, "regenerated image")
                except Exception as exc:
                    logger.warning(
                        "Failed to persist regenerated XHS image: {}",
                        exc,
                    )

        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_image_regenerate",
            description="XHS image regeneration",
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
            message="重新生成成功",
            data=result_data,
        )
    except Exception as exc:
        logger.exception("Failed to regenerate XHS image: {}", exc)
        raise_xhs_error(exc, "单页重新生图")


@router.post(
    "/image/batch_grid/regenerate",
    response_model=Response[dict],
    summary="省钱模式批量重绘选中页面 (2-4 张)",
    dependencies=[Depends(require_image_enabled)],
)
async def regenerate_batch_grid_subset(
    request: BatchGridRegenerateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """Regenerate a subset (2/3/4 pages) via one composite API call.

    See :class:`BatchGridRegenerateRequest` / :class:`BatchGridRegenerateResponse`
    for payload shape. Backend picks the grid layout automatically. Provider
    or config failures are returned as failed cell results, without silently
    downgrading selected pages to extra per_page image calls.
    """
    logger.info(
        "/xhs/image/batch_grid/regenerate: user={}, task_id={}, "
        "page_indexes={}, engine={}",
        current_user.id,
        request.task_id,
        request.page_indexes,
        request.image_engine,
    )

    try:
        credit_cost = calculate_image_credit_cost(
            "batch_grid",
            len(request.page_indexes),
            image_quality=request.image_quality,
            api_calls=1,
        )
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        result = await _image_service.regenerate_batch_grid(
            all_pages=request.pages,
            page_indexes=request.page_indexes,
            outline=request.outline,
            user_topic=request.user_topic,
            image_engine=request.image_engine,
            image_quality=request.image_quality,
            image_style=request.image_style,
            negative_prompt=request.negative_prompt,
            extra_params=request.extra_params,
            user_id=current_user.id,
            style_prompt=request.style_prompt,
            negative_style_prompt=request.negative_style_prompt,
            grid_config=request.grid_config,
        )

        if request.task_id:
            task = await get_task_if_provided(db, request.task_id, current_user.id)
            if task:
                try:
                    for cell in result["cells"]:
                        if cell.get("status") != "success":
                            continue
                        await xhs_task.update_page_field(
                            db,
                            task=task,
                            page_index=cell["page_index"],
                            updates={
                                "image_url": cell.get("original_url") or "",
                                "thumbnail_url": cell.get("thumbnail_url") or "",
                                "original_url": cell.get("original_url") or "",
                            },
                        )
                    await save_task_safe(db, "batch_grid regenerated images")
                except Exception as exc:
                    logger.warning(
                        "Failed to persist batch_grid regenerated XHS images: {}",
                        exc,
                    )

        success = result.get("success", 0)
        failed = result.get("failed", 0)
        if success > 0:
            await deduct_xhs_credits(
                db,
                current_user.id,
                credit_cost,
                transaction_type="usage_image_regenerate",
                description="XHS batch-grid image regeneration",
                reference_id=(
                    f"{request.task_id}:{','.join(str(i) for i in request.page_indexes)}"
                    if request.task_id is not None
                    else None
                ),
            )
            await db.commit()

        if failed == 0:
            message = f"成功重绘 {success} 张"
        elif success == 0:
            message = "全部重绘失败"
        else:
            message = f"{success} 张成功, {failed} 张失败"

        return Response(
            code=200,
            # Transport success means the batch request was handled. Per-cell
            # failures are reported in data.cells/data.failed so the frontend
            # can keep rendering page-level statuses instead of receiving the
            # raw envelope and treating it as an exception.
            success=True,
            message=message,
            data=result,
        )
    except ValueError as exc:
        logger.warning("batch_grid regenerate bad request: {}", exc)
        raise_xhs_error(exc, "批量重绘")
    except Exception as exc:
        logger.exception("Failed to batch regenerate XHS images: {}", exc)
        raise_xhs_error(exc, "批量重绘")
