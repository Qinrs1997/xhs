"""XHS 任务文案端点

接口列表:
- PUT /tasks/{id}/copywriting   保存/更新任务文案
- GET /tasks/{id}/copywriting   获取任务文案
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.schemas.response import Response
from app.schemas.xhs_task import CopywritingData

router = APIRouter()


@router.put(
    "/tasks/{task_id}/copywriting",
    response_model=Response[dict],
    summary="保存/更新任务文案",
    description="保存 AI 生成的小红书发布文案到任务。",
)
async def save_copywriting(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
    data: CopywritingData,
) -> Any:
    """保存文案到任务"""
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    task.copywriting = data.model_dump(exclude_none=True)
    task.updater_id = current_user.id
    db.add(task)
    await db.commit()

    return Response(
        code=200,
        success=True,
        message="文案保存成功",
        data={"id": task.id, "copywriting_saved": True},
    )


@router.get(
    "/tasks/{task_id}/copywriting",
    response_model=Response[dict],
    summary="获取任务文案",
)
async def get_copywriting(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
) -> Any:
    """获取任务文案"""
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    copywriting = dict(task.copywriting) if task.copywriting else {}
    copywriting["created_at"] = (
        task.created_at.isoformat() if task.created_at else None
    )

    return Response(code=200, success=True, message="获取成功", data=copywriting)
