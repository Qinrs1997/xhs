"""用户-部门分配接口

- POST   /users/assign                              —— 分配单个部门
- POST   /users/batch-assign                        —— 批量分配（支持清除已有）
- DELETE /users/{user_id}/departments/{dept_id}     —— 移除用户
- GET    /users/{user_id}/departments               —— 用户所属部门
- GET    /{department_id}/users                     —— 部门成员（支持 recursive）
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser
from app.core.audit import AuditAction, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.exceptions import BadRequestError, NotFoundError
from app.crud import user as user_crud
from app.crud.department import department as dept_crud
from app.crud.department import user_department as ud_crud
from app.models.user import User
from app.schemas.department import (
    DepartmentBrief,
    UserDepartmentAssign,
    UserDepartmentBatchAssign,
    UserDepartmentResponse,
)
from app.schemas.response import Response

router = APIRouter()


def _department_brief(dept) -> DepartmentBrief | None:
    """从 ORM Department 构造 DepartmentBrief（允许 None）"""
    if not dept:
        return None
    return DepartmentBrief(id=dept.id, name=dept.name, code=dept.code, level=dept.level)


@router.post(
    "/users/assign",
    response_model=Response[UserDepartmentResponse],
    summary="分配用户到部门",
    description="将用户分配到指定部门（仅管理员），支持一人多部门",
)
async def assign_user_to_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    assign_in: UserDepartmentAssign,
    audit: AuditLogger = Depends(
        get_audit_logger(
            action=AuditAction.DEPARTMENT_USER_ASSIGN, description="分配用户到部门"
        )
    ),
) -> Any:
    """分配用户到部门

    - 支持一人多部门
    - 可设置主部门（is_primary=true）
    - 可指定职位
    """
    user = await user_crud.get(db, id=assign_in.user_id)
    if not user:
        raise NotFoundError("用户不存在")

    dept = await dept_crud.get(db, id=assign_in.department_id)
    if not dept:
        raise NotFoundError("部门不存在")
    if not dept.is_active:
        raise BadRequestError("部门已禁用，无法分配用户")

    link = await ud_crud.assign_user(
        db,
        user_id=assign_in.user_id,
        department_id=assign_in.department_id,
        is_primary=assign_in.is_primary,
        position=assign_in.position,
    )

    await audit.log(
        detail={
            "user_id": assign_in.user_id,
            "department_id": assign_in.department_id,
            "is_primary": assign_in.is_primary,
        }
    )

    return Response(
        code=200,
        success=True,
        message="分配成功",
        data=UserDepartmentResponse(
            id=link.id,
            user_id=link.user_id,
            department_id=link.department_id,
            is_primary=link.is_primary,
            position=link.position,
            department=_department_brief(dept),
        ),
    )


@router.post(
    "/users/batch-assign",
    response_model=Response[list[UserDepartmentResponse]],
    summary="批量分配部门",
    description="为用户批量分配多个部门（仅管理员）",
)
async def batch_assign_user_departments(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    assign_in: UserDepartmentBatchAssign,
    audit: AuditLogger = Depends(
        get_audit_logger(
            action=AuditAction.DEPARTMENT_USER_ASSIGN, description="批量分配用户部门"
        )
    ),
) -> Any:
    """批量分配用户到多个部门

    - clear_existing=true: 清除现有部门后重新分配
    - clear_existing=false: 追加到现有部门（默认）
    """
    user = await user_crud.get(db, id=assign_in.user_id)
    if not user:
        raise NotFoundError("用户不存在")

    depts = await dept_crud.get_by_ids(db, ids=assign_in.department_ids)
    dept_map = {d.id: d for d in depts}
    for dept_id in assign_in.department_ids:
        dept = dept_map.get(dept_id)
        if not dept:
            raise NotFoundError(f"部门 ID {dept_id} 不存在")
        if not dept.is_active:
            raise BadRequestError(f"部门 '{dept.name}' 已禁用")

    if (
        assign_in.primary_department_id
        and assign_in.primary_department_id not in assign_in.department_ids
    ):
        raise BadRequestError("主部门必须在部门列表中")

    links = await ud_crud.batch_assign_user(
        db,
        user_id=assign_in.user_id,
        department_ids=assign_in.department_ids,
        primary_department_id=assign_in.primary_department_id,
        clear_existing=assign_in.clear_existing,
    )

    await audit.log(
        detail={
            "user_id": assign_in.user_id,
            "department_ids": assign_in.department_ids,
            "count": len(links),
        }
    )

    link_dept_ids = [link.department_id for link in links]
    if link_dept_ids:
        link_depts = await dept_crud.get_by_ids(db, ids=link_dept_ids)
        link_dept_map = {d.id: d for d in link_depts}
    else:
        link_dept_map = {}

    result = [
        UserDepartmentResponse(
            id=link.id,
            user_id=link.user_id,
            department_id=link.department_id,
            is_primary=link.is_primary,
            position=link.position,
            department=_department_brief(link_dept_map.get(link.department_id)),
        )
        for link in links
    ]

    return Response(
        code=200,
        success=True,
        message=f"已分配 {len(result)} 个部门",
        data=result,
    )


@router.delete(
    "/users/{user_id}/departments/{department_id}",
    response_model=Response[dict],
    summary="从部门移除用户",
    description="将用户从指定部门移除（仅管理员）",
)
async def remove_user_from_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    user_id: int,
    department_id: int,
    audit: AuditLogger = Depends(
        get_audit_logger(
            action=AuditAction.DEPARTMENT_USER_REMOVE, description="从部门移除用户"
        )
    ),
) -> Any:
    """从部门移除用户"""
    success = await ud_crud.remove_user_from_department(
        db, user_id=user_id, department_id=department_id
    )

    await audit.log(detail={"user_id": user_id, "department_id": department_id})

    if not success:
        raise NotFoundError("用户不在该部门中")

    return Response(
        code=200,
        success=True,
        message="移除成功",
        data={"user_id": user_id, "department_id": department_id},
    )


@router.get(
    "/users/{user_id}/departments",
    response_model=Response[list[UserDepartmentResponse]],
    summary="获取用户的部门",
    description="获取指定用户所属的所有部门",
)
async def get_user_departments(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    user_id: int,
) -> Any:
    """获取用户的所有部门"""
    if not current_user.is_superuser and current_user.id != user_id:
        user_id = current_user.id

    links = await ud_crud.get_user_departments(db, user_id=user_id)

    result = [
        UserDepartmentResponse(
            id=link.id,
            user_id=link.user_id,
            department_id=link.department_id,
            is_primary=link.is_primary,
            position=link.position,
            department=_department_brief(link.department),
        )
        for link in links
    ]

    return Response(code=200, success=True, message="获取成功", data=result)


@router.get(
    "/{department_id}/users",
    response_model=Response[dict],
    summary="获取部门成员",
    description="获取指定部门的所有成员（默认包含子部门）",
)
async def get_department_users(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    department_id: int,
    recursive: bool = Query(True, description="是否包含子部门成员"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Any:
    """获取部门成员"""
    skip = (page - 1) * page_size
    links, total = await ud_crud.get_department_users(
        db,
        department_id=department_id,
        recursive=recursive,
        skip=skip,
        limit=page_size,
    )

    items = [
        {
            "id": link.id,
            "user_id": link.user_id,
            "is_primary": link.is_primary,
            "position": link.position,
            "username": link.user.username if link.user else None,
            "full_name": link.user.full_name if link.user else None,
            "email": link.user.email if link.user else None,
        }
        for link in links
    ]

    return Response(
        code=200,
        success=True,
        message="获取成功",
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    )
