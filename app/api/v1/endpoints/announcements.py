"""公告管理接口 (异步版) - 支持部门定向发送

提供公告的增删改查功能。
- 管理员可以看到所有公告
- 普通用户只能看到：target_type='all' 或 指定了自己所属部门的公告
"""
from typing import Any, List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.user import User
from app.schemas.announcement import (
    AnnouncementOut,
    AnnouncementCreate,
    AnnouncementUpdate,
    AnnouncementList,
    AnnouncementDetail,
    DepartmentBrief,
)
from app.schemas.response import Response
from app.crud.announcement import announcement as announcement_crud
from app.crud.department import user_department as ud_crud

router = APIRouter()


async def get_user_dept_ids(db: AsyncSession, user_id: int) -> List[int]:
    """获取用户所属的部门 ID 列表"""
    links = await ud_crud.get_user_departments(db, user_id=user_id)
    return [link.department_id for link in links]


@router.get("", response_model=Response[AnnouncementList], summary="公告列表")
async def list_announcements(
    db: AsyncSession = Depends(get_async_db),
    keyword: str = Query(None, description="搜索关键词（标题/内容）"),
    published_only: bool = Query(True, description="是否只看已发布"),
    type: str = Query(None, description="按类型筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    获取公告列表

    - 管理员：可以看到所有公告
    - 普通用户：只能看到 target_type='all' 或 指定了自己所属部门的公告
    """
    skip = (page - 1) * page_size

    # 获取用户的部门 ID 列表
    user_dept_ids = None
    if not current_user.is_superuser:
        user_dept_ids = await get_user_dept_ids(db, current_user.id)

    items, total = await announcement_crud.get_list(
        db,
        keyword=keyword,
        published_only=published_only,
        type=type,
        skip=skip,
        limit=page_size,
        is_superuser=current_user.is_superuser,
        user_dept_ids=user_dept_ids
    )

    return Response(
        message="获取成功",
        data=AnnouncementList(total=total, items=items)
    )


@router.get("/{announcement_id}", response_model=Response[AnnouncementDetail], summary="公告详情")
async def get_announcement(
    announcement_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """获取公告详情（包含目标部门信息）"""
    # 获取用户的部门 ID 列表
    user_dept_ids = None
    if not current_user.is_superuser:
        user_dept_ids = await get_user_dept_ids(db, current_user.id)

    ann, can_view = await announcement_crud.can_view(
        db,
        id=announcement_id,
        is_superuser=current_user.is_superuser,
        user_dept_ids=user_dept_ids
    )

    if not ann:
        raise NotFoundError("公告不存在")

    if not can_view:
        raise PermissionDeniedError("无权查看该公告")

    # 获取包含部门信息的完整数据
    ann_with_depts = await announcement_crud.get_with_departments(db, id=announcement_id)

    # 构建响应
    target_departments = []
    if ann_with_depts and ann_with_depts.target_departments:
        for td in ann_with_depts.target_departments:
            if td.department:
                target_departments.append(DepartmentBrief(
                    id=td.department.id,
                    name=td.department.name,
                    code=td.department.code
                ))

    return Response(
        message="获取成功",
        data=AnnouncementDetail(
            id=ann.id,
            title=ann.title,
            content=ann.content,
            type=ann.type,
            is_published=ann.is_published,
            published_at=ann.published_at,
            author_id=ann.author_id,
            author_name=ann.author_name,
            target_type=ann.target_type,
            target_dept_ids=ann.target_dept_ids,
            target_departments=target_departments,
            created_at=ann.created_at,
            updated_at=ann.updated_at,
        )
    )


@router.post("", response_model=Response[AnnouncementOut], status_code=status.HTTP_201_CREATED, summary="创建公告")
async def create_announcement(
    *,
    db: AsyncSession = Depends(get_async_db),
    ann_in: AnnouncementCreate,
    current_user: User = Depends(deps.get_current_superuser),
) -> Any:
    """
    创建公告 (仅限管理员)

    参数说明：
    - target_type: 'all' 发给所有人，'dept' 发给指定部门
    - dept_ids: 当 target_type='dept' 时，指定目标部门 ID 列表
    """
    ann = await announcement_crud.create_announcement(
        db,
        obj_in=ann_in,
        author_id=current_user.id,
        author_name=current_user.full_name or current_user.username,
    )

    return Response(code=201, message="创建成功", data=ann)


@router.put("/{announcement_id}", response_model=Response[AnnouncementOut], summary="更新公告")
async def update_announcement(
    *,
    announcement_id: int,
    db: AsyncSession = Depends(get_async_db),
    ann_in: AnnouncementUpdate,
    current_user: User = Depends(deps.get_current_superuser),
) -> Any:
    """
    更新公告 (仅限管理员)

    可以修改 target_type 和 dept_ids 来调整发送范围。
    """
    ann = await announcement_crud.get(db, id=announcement_id)
    if not ann:
        raise NotFoundError("公告不存在")

    ann = await announcement_crud.update_announcement(
        db,
        db_obj=ann,
        obj_in=ann_in,
        author_id=current_user.id,
        author_name=current_user.full_name or current_user.username,
    )

    return Response(message="更新成功", data=ann)


@router.delete("/{announcement_id}", response_model=Response[None], summary="删除公告")
async def delete_announcement(
    announcement_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(deps.get_current_superuser),
) -> Any:
    """删除公告 (仅限管理员)"""
    ann = await announcement_crud.get(db, id=announcement_id)
    if not ann:
        raise NotFoundError("公告不存在")

    await announcement_crud.delete(db, id=announcement_id)

    return Response(message="删除成功")

