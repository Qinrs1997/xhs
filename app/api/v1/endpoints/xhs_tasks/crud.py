"""XHS 任务标准 CRUD 端点

接口列表:
- GET    /tasks          获取任务列表(分页 + 关键字 + 状态筛选)
- POST   /tasks          创建任务(标准 REST)
- GET    /tasks/{id}     获取任务详情(含搜索关联)
- PUT    /tasks/{id}     更新任务(标准 REST)
- DELETE /tasks/{id}     删除任务 + 异步清理本地图片
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.ai.services.xhs.utils import normalize_page_order
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError
from app.core.logger import logger
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.schemas.response import Response
from app.schemas.xhs_task import (
    TaskOperationResponse,
    TaskStatus,
    XHSTaskBrief,
    XHSTaskCreate,
    XHSTaskList,
    XHSTaskResponse,
    XHSTaskUpdate,
)

from ._shared import _cleanup_task_files, _extract_search_id

router = APIRouter()


@router.get(
    "/tasks",
    response_model=Response[XHSTaskList],
    summary="获取任务列表",
)
async def list_tasks(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: TaskStatus | None = Query(None, description="状态筛选"),
    keyword: str | None = Query(None, description="关键词搜索"),
) -> Any:
    """获取任务列表(分页)"""
    skip = (page - 1) * page_size
    items, total = await xhs_task.get_by_user(
        db,
        user_id=current_user.id,
        status=status,
        keyword=keyword,
        skip=skip,
        limit=page_size,
    )

    brief_items = []
    for item in items:
        slim_pages = None
        if item.pages:
            ordered_pages = normalize_page_order(item.pages)
            slim_pages = [
                {
                    "page_num": p.get("page_num", i + 1),
                    "page_type": p.get("page_type", "content"),
                    "thumbnail_url": p.get("thumbnail_url") or p.get("image_url", ""),
                    "original_url": p.get("original_url", ""),
                    "title": p.get("title", ""),
                }
                for i, p in enumerate(ordered_pages)
            ]

        brief_items.append(
            XHSTaskBrief(
                id=item.id,
                title=item.title,
                topic=item.topic[:100] + "..." if len(item.topic) > 100 else item.topic,
                status=item.status,
                page_count=item.page_count,
                style=item.style,
                template_id=item.template_id,
                has_copywriting=bool(item.copywriting),
                pages=slim_pages,
                search_id=_extract_search_id(item),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )

    pages_count = (total + page_size - 1) // page_size if page_size > 0 else 0

    return Response(
        code=200,
        success=True,
        message="获取成功",
        data=XHSTaskList(
            items=brief_items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages_count,
        ),
    )


@router.get(
    "/tasks/{task_id}",
    response_model=Response[XHSTaskResponse],
    summary="获取任务详情",
)
async def get_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
) -> Any:
    """获取任务详情(含搜索关联 ID)"""
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    task_data = XHSTaskResponse.model_validate(task)
    if task_data.pages:
        task_data.pages = normalize_page_order(task_data.pages)
    task_data.search_id = _extract_search_id(task)

    return Response(code=200, success=True, message="获取成功", data=task_data)


@router.delete(
    "/tasks/{task_id}",
    response_model=Response[TaskOperationResponse],
    summary="删除任务",
)
async def delete_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
) -> Any:
    """删除任务(同时异步清理本地图片文件)"""
    deleted_task = await xhs_task.delete_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not deleted_task:
        raise NotFoundError("任务不存在或无权删除")

    def _on_cleanup_done(t: asyncio.Task) -> None:
        if t.exception():
            logger.error("清理任务 {} 文件异常: {}", task_id, t.exception())

    cleanup = asyncio.create_task(_cleanup_task_files(deleted_task.pages, task_id))
    cleanup.add_done_callback(_on_cleanup_done)

    return Response(
        code=200,
        success=True,
        message="删除成功",
        data=TaskOperationResponse(success=True, task_id=task_id, message="删除成功"),
    )


@router.post(
    "/tasks",
    response_model=Response[XHSTaskResponse],
    status_code=status.HTTP_201_CREATED,
    summary="创建任务(标准 REST)",
)
async def create_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_data: XHSTaskCreate,
) -> Any:
    """创建任务"""
    task = await xhs_task.create_for_user(
        db, obj_in=task_data, user_id=current_user.id
    )
    return Response(
        code=201,
        success=True,
        message="创建成功",
        data=XHSTaskResponse.model_validate(task),
    )


@router.put(
    "/tasks/{task_id}",
    response_model=Response[XHSTaskResponse],
    summary="更新任务(标准 REST)",
)
async def update_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    task_id: int,
    task_data: XHSTaskUpdate,
) -> Any:
    """更新任务"""
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    task = await xhs_task.update_task(
        db, task=task, obj_in=task_data, user_id=current_user.id
    )
    return Response(
        code=200,
        success=True,
        message="更新成功",
        data=XHSTaskResponse.model_validate(task),
    )
