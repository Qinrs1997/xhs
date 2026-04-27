"""部门详情 / 树 / 更新 / 删除

（根路径 POST "" / GET "" 见 `departments/__init__.py`，因为 FastAPI 不允许
"include_router 的 prefix 与 path 同时为空"。）

- GET    /tree             —— 树形结构（缓存 60s）
- GET    /{department_id}  —— 详情
- PUT    /{department_id}  —— 更新
- DELETE /{department_id}  —— 删除（需无子部门/无成员）
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser
from app.core.audit import AuditAction, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.exceptions import BadRequestError, DuplicateError, NotFoundError
from app.crud.department import department as dept_crud
from app.crud.department import user_department as ud_crud
from app.models.user import User
from app.schemas.department import (
    DepartmentResponse,
    DepartmentUpdate,
)
from app.schemas.response import Response

from ._helpers import invalidate_tree_cache

router = APIRouter()


@router.get(
    "/tree",
    response_model=Response[list[dict]],
    summary="获取部门树",
    description="获取树形结构的部门列表",
)
async def get_department_tree(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    include_inactive: bool = Query(False, description="是否包含禁用部门"),
) -> Any:
    """获取部门树（缓存 60 秒）"""
    if include_inactive and not current_user.is_superuser:
        include_inactive = False

    from app.core.cache import cache
    cache_key = f"dept_tree:{include_inactive}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return Response(code=200, success=True, message="获取成功", data=cached)

    tree = await dept_crud.get_tree(db, include_inactive=include_inactive)
    await cache.set(cache_key, tree, ttl=60)

    return Response(code=200, success=True, message="获取成功", data=tree)


@router.get(
    "/{department_id}",
    response_model=Response[DepartmentResponse],
    summary="获取部门详情",
)
async def get_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    department_id: int,
) -> Any:
    """获取部门详情"""
    dept = await dept_crud.get(db, id=department_id)
    if not dept:
        raise NotFoundError("部门不存在")

    return Response(
        code=200,
        success=True,
        message="获取成功",
        data=DepartmentResponse.model_validate(dept),
    )


@router.put(
    "/{department_id}",
    response_model=Response[DepartmentResponse],
    summary="更新部门",
    description="更新部门信息（仅管理员）",
)
async def update_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    department_id: int,
    dept_in: DepartmentUpdate,
    audit: AuditLogger = Depends(
        get_audit_logger(action=AuditAction.DEPARTMENT_UPDATE, description="更新部门")
    ),
) -> Any:
    """更新部门"""
    dept = await dept_crud.get(db, id=department_id)
    if not dept:
        raise NotFoundError("部门不存在")

    if dept_in.code and dept_in.code != dept.code:
        existing = await dept_crud.get_by_code(db, code=dept_in.code)
        if existing:
            raise DuplicateError(f"部门编码 '{dept_in.code}' 已存在")

    if dept_in.parent_id == department_id:
        raise BadRequestError("不能将部门设为自己的子部门")

    dept = await dept_crud.update_department(
        db, dept=dept, obj_in=dept_in, updater_id=current_user.id
    )

    await audit.log(detail={"department_id": dept.id, "changes": dept_in.model_dump(exclude_unset=True)})
    await invalidate_tree_cache()

    return Response(
        code=200,
        success=True,
        message="更新成功",
        data=DepartmentResponse.model_validate(dept),
    )


@router.delete(
    "/{department_id}",
    response_model=Response[dict],
    summary="删除部门",
    description="删除部门（仅管理员，需确保无子部门和成员）",
)
async def delete_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    department_id: int,
    audit: AuditLogger = Depends(
        get_audit_logger(action=AuditAction.DEPARTMENT_DELETE, description="删除部门")
    ),
) -> Any:
    """删除部门"""
    dept = await dept_crud.get(db, id=department_id)
    if not dept:
        raise NotFoundError("部门不存在")

    if await dept_crud.has_children(db, department_id=department_id):
        raise BadRequestError("请先删除子部门")

    _, count = await ud_crud.get_department_users(db, department_id=department_id, limit=1)
    if count > 0:
        raise BadRequestError("请先移除部门成员")

    await dept_crud.delete(db, id=department_id)

    await audit.log(detail={"department_id": department_id})
    await invalidate_tree_cache()

    return Response(
        code=200,
        success=True,
        message="删除成功",
        data={"id": department_id},
    )
