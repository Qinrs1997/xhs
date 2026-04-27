"""XHS 任务保存端点

提供 POST /tasks/save 接口,支持创建、完整更新与 autosave 模式。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.ai.services.xhs.utils import derive_page_title, get_page_num, normalize_page_order
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.core.timezone import now_utc
from app.crud.search_history import search_history_crud
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.schemas.response import Response
from app.schemas.xhs_task import (
    TaskOperationResponse,
    TaskStatus,
    XHSTaskCreate,
    XHSTaskSave,
    XHSTaskUpdate,
)

from ._shared import _merge_image_fields

router = APIRouter()


def _has_page_image(page: dict[str, Any]) -> bool:
    return bool(
        page.get("image_url") or page.get("thumbnail_url") or page.get("original_url")
    )


def _derive_status_from_pages(pages: list[dict[str, Any]]) -> TaskStatus | None:
    if not pages:
        return None

    statuses = [
        (page.get("extra") or {}).get("status")
        if isinstance(page.get("extra") or {}, dict)
        else None
        for page in pages
    ]

    if any(status == "failed" for status in statuses):
        return TaskStatus.FAILED
    if any(status == "running" for status in statuses):
        return TaskStatus.GENERATING
    if all(status == "success" or _has_page_image(page) for status, page in zip(statuses, pages, strict=False)):
        return TaskStatus.COMPLETED
    if any(_has_page_image(page) for page in pages):
        return TaskStatus.GENERATING
    return None


def _normalize_page_title(page: dict[str, Any], page_num: int) -> dict[str, Any]:
    normalized = dict(page)
    extra = normalized.get("extra")
    extra_dict = dict(extra) if isinstance(extra, dict) else {}

    title = str(normalized.get("title") or extra_dict.get("title") or "").strip()
    if not title:
        title = derive_page_title(
            str(normalized.get("content") or ""),
            fallback=f"第 {page_num} 页",
        )

    if title:
        normalized["title"] = title
        extra_dict["title"] = title
        normalized["extra"] = extra_dict

    return normalized


def _normalize_pages_for_save(pages: list[Any] | None) -> list[dict[str, Any]] | None:
    if not pages:
        return None
    normalized: list[dict[str, Any]] = []
    for index, page in enumerate(pages):
        page_dict = page.model_dump() if hasattr(page, "model_dump") else dict(page)
        page_num = get_page_num(page_dict, index + 1)
        page_dict["page_num"] = page_num
        normalized.append(_normalize_page_title(page_dict, page_num))
    return normalize_page_order(normalized)


@router.post(
    "/tasks/save",
    response_model=Response[TaskOperationResponse],
    summary="保存任务",
    description="创建新任务或更新已有任务。autosave=true 时仅更新 pages。",
)
async def save_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_data: XHSTaskSave,
) -> Any:
    """保存任务(创建或更新,支持 autosave 模式)"""
    now = now_utc()

    if task_data.task_id:
        task = await xhs_task.get_user_task(
            db, task_id=task_data.task_id, user_id=current_user.id
        )
        if not task:
            raise NotFoundError("任务不存在或无权访问")

        if task_data.autosave:
            # 轻量模式:仅更新 pages 和 last_autosave_at
            if task_data.pages:
                new_pages = _normalize_pages_for_save(task_data.pages) or []
                # 合并图片字段,避免覆盖后端刚写入的图片 URL
                existing_pages = task.pages or []
                _merge_image_fields(existing_pages, new_pages)
                task.pages = new_pages
                task.page_count = len(task_data.pages)
            task.last_autosave_at = now
            task.updater_id = current_user.id
            db.add(task)
            await db.commit()

            return Response(
                code=200, success=True, message="自动保存成功",
                data=TaskOperationResponse(
                    success=True, task_id=task.id,
                    message="自动保存成功", saved_at=now,
                ),
            )

        # 完整更新
        merged_pages = None
        if task_data.pages:
            merged_pages = _normalize_pages_for_save(task_data.pages)
            # Full save must not wipe image URLs just written by the SSE worker.
            _merge_image_fields(task.pages or [], merged_pages)

        status = task_data.status
        if merged_pages and status in {TaskStatus.DRAFT, TaskStatus.PENDING}:
            status = _derive_status_from_pages(merged_pages) or status

        update_data = XHSTaskUpdate(
            title=task_data.title,
            topic=task_data.topic,
            pages=merged_pages if merged_pages is not None else task_data.pages,
            style=task_data.style,
            model=task_data.model,
            status=status,
            template_id=task_data.template_id,
        )
        task = await xhs_task.update_task(
            db, task=task, obj_in=update_data, user_id=current_user.id
        )

        if task_data.search_id:
            try:
                await search_history_crud.link_task_if_not_exists(
                    db,
                    search_history_id=task_data.search_id,
                    task_id=task.id,
                    user_id=current_user.id,
                )
            except Exception as link_err:
                logger.warning("保存任务时关联搜索记录失败: {}", link_err)

        return Response(
            code=200, success=True, message="任务更新成功",
            data=TaskOperationResponse(
                success=True, task_id=task.id, message="更新成功",
            ),
        )

    # 创建新任务
    create_pages = _normalize_pages_for_save(task_data.pages)
    create_data = XHSTaskCreate(
        title=task_data.title,
        topic=task_data.topic,
        pages=create_pages,
        style=task_data.style,
        model=task_data.model,
        status=task_data.status,
        template_id=task_data.template_id,
    )
    # 先递增模板使用次数(flush 但不 commit,和 create_for_user 合为一次事务)
    if task_data.template_id:
        from app.crud.xhs_template import xhs_template
        await xhs_template.increment_use_count(
            db, template_id=task_data.template_id
        )

    task = await xhs_task.create_for_user(
        db, obj_in=create_data, user_id=current_user.id
    )

    if task_data.search_id:
        try:
            await search_history_crud.link_task_if_not_exists(
                db,
                search_history_id=task_data.search_id,
                task_id=task.id,
                user_id=current_user.id,
            )
        except Exception as link_err:
            logger.warning("创建任务时关联搜索记录失败: {}", link_err)

    return Response(
        code=200, success=True, message="任务创建成功",
        data=TaskOperationResponse(
            success=True, task_id=task.id, message="创建成功",
        ),
    )
