"""XHS 任务轻量自动保存端点

接口列表:
- PUT /tasks/{id}/autosave   轻量自动保存(前端 300ms 防抖调用)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.ai.services.xhs.utils import normalize_page_order
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError
from app.core.timezone import now_utc
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.schemas.response import Response

from ._shared import AutosaveRequest, _merge_image_fields

router = APIRouter()


@router.put(
    "/tasks/{task_id}/autosave",
    response_model=Response[dict],
    summary="轻量自动保存(独立端点)",
    description="仅更新 pages 数据,不改变 status 等元信息。前端 300ms 防抖调用。",
)
async def autosave_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
    data: AutosaveRequest,
) -> Any:
    """轻量自动保存(Pydantic 校验 pages)"""
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    if data.pages:
        existing_pages = task.pages or []
        new_pages = normalize_page_order(data.pages)
        _merge_image_fields(existing_pages, new_pages)
        task.pages = normalize_page_order(new_pages)
        task.page_count = len(new_pages)

    now = now_utc()
    task.last_autosave_at = now
    task.updater_id = current_user.id
    db.add(task)
    await db.commit()

    return Response(
        code=200,
        success=True,
        message="自动保存成功",
        data={"saved_at": now.isoformat()},
    )
