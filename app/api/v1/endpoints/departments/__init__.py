"""部门管理 API 子包

按职责拆为两个子模块（加一组根路径端点）：

- **根路径端点**（POST "" / GET ""）直接挂在本包 router 上，
  因为 FastAPI 禁止 `include_router` 时 prefix 与 path 同时为空。
- `crud.py`         — /tree / /{id} 详情 / 更新 / 删除（4 端点）
- `user_assign.py`  — 用户 ↔ 部门 分配相关（5 端点）

对外仍以 `departments.router` 统一导出，URL 与拆分前完全兼容。
"""
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser
from app.core.audit import AuditAction, AuditLogger, get_audit_logger
from app.core.database import get_async_db
from app.core.exceptions import DuplicateError, NotFoundError
from app.crud.department import department as dept_crud
from app.models.user import User
from app.schemas.department import (
    DepartmentCreate,
    DepartmentList,
    DepartmentResponse,
)
from app.schemas.response import Response

from ._helpers import invalidate_tree_cache
from .crud import router as crud_router
from .user_assign import router as user_assign_router

router = APIRouter()


# ==================== 根路径 ====================


@router.post(
    "",
    response_model=Response[DepartmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="创建部门",
    description="创建新部门（仅管理员）",
)
async def create_department(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
    dept_in: DepartmentCreate,
    audit: AuditLogger = Depends(
        get_audit_logger(action=AuditAction.DEPARTMENT_CREATE, description="创建部门")
    ),
) -> Any:
    """创建部门"""
    existing = await dept_crud.get_by_code(db, code=dept_in.code)
    if existing:
        raise DuplicateError(f"部门编码 '{dept_in.code}' 已存在")

    if dept_in.parent_id:
        parent = await dept_crud.get(db, id=dept_in.parent_id)
        if not parent:
            raise NotFoundError("父部门不存在")

    dept = await dept_crud.create_department(
        db, obj_in=dept_in, creator_id=current_user.id
    )

    await audit.log(detail={"department_id": dept.id, "name": dept.name, "code": dept.code})
    await invalidate_tree_cache()

    return Response(
        code=201,
        success=True,
        message="部门创建成功",
        data=DepartmentResponse.model_validate(dept),
    )


@router.get(
    "",
    response_model=Response[DepartmentList],
    summary="获取部门列表",
    description="获取所有部门列表",
)
async def list_departments(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
) -> Any:
    """获取部门列表"""
    skip = (page - 1) * page_size
    items, total = await dept_crud.get_all_active(db, skip=skip, limit=page_size)

    return Response(
        code=200,
        success=True,
        message="获取成功",
        data=DepartmentList(
            items=[DepartmentResponse.model_validate(d) for d in items],
            total=total,
        ),
    )


# ==================== 子路由挂载 ====================
# ⚠️ 顺序：user_assign 先，因为 `/users/assign`、`/users/batch-assign` 等
# 为精确路径；crud 里有 `/{department_id}` 通配，必须放后面以免抢先匹配。
router.include_router(user_assign_router)
router.include_router(crud_router)

__all__ = ["router"]
