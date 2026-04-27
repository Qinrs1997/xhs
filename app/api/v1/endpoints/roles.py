"""异步角色与用户角色管理 API"""
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.api.deps import get_current_superuser
from app.core.utils import log_request
from app.core.exceptions import NotFoundError, DuplicateError
from app.crud import role as role_crud, user as user_crud
from app.schemas import (
    Role,
    RoleCreate,
    RoleUpdate,
    RoleList,
    Response,
)

router = APIRouter()


@router.get(
    "",
    response_model=Response[RoleList],
    summary="角色列表",
    dependencies=[Depends(log_request("admin action"))],
)
async def list_roles(
    db: AsyncSession = Depends(get_async_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    current_user=Depends(get_current_superuser),
) -> Any:
    """获取角色列表"""
    roles = await role_crud.get_multi(db, skip=skip, limit=limit)
    total = await role_crud.count(db)
    return Response(
        code=200,
        message="获取成功",
        data=RoleList(total=total, items=list(roles))
    )


@router.post(
    "",
    response_model=Response[Role],
    status_code=200,
    summary="创建角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def create_role(
    *,
    db: AsyncSession = Depends(get_async_db),
    role_in: RoleCreate,
    current_user=Depends(get_current_superuser),
) -> Any:
    """创建新角色"""
    exists = await role_crud.get_by_name(db, name=role_in.name)
    if exists:
        raise DuplicateError("角色名称已存在")
    role = await role_crud.create(db, obj_in=role_in)
    return Response(code=200, message="创建成功", data=role)


@router.put(
    "/{role_id}",
    response_model=Response[Role],
    summary="更新角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def update_role(
    *,
    db: AsyncSession = Depends(get_async_db),
    role_id: int,
    role_in: RoleUpdate,
    current_user=Depends(get_current_superuser),
) -> Any:
    """更新角色"""
    role = await role_crud.get(db, id=role_id)
    if not role:
        raise NotFoundError("角色不存在")
    # 名称唯一校验
    if role_in.name:
        exists = await role_crud.get_by_name(db, name=role_in.name)
        if exists and exists.id != role_id:
            raise DuplicateError("角色名称已存在")
    role = await role_crud.update(db, db_obj=role, obj_in=role_in)
    return Response(code=200, message="更新成功", data=role)


@router.delete(
    "/{role_id}",
    response_model=Response[None],
    summary="删除角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_superuser),
) -> Any:
    """删除角色"""
    role = await role_crud.get(db, id=role_id)
    if not role:
        raise NotFoundError("角色不存在")
    await role_crud.delete(db, id=role_id)
    return Response(code=200, message="删除成功")


@router.post(
    "/assign",
    response_model=Response[None],
    summary="为用户分配角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def assign_role(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: int,
    role_id: int,
    current_user=Depends(get_current_superuser),
) -> Any:
    """为用户分配角色"""
    user = await user_crud.get(db, id=user_id)
    if not user:
        raise NotFoundError("用户不存在")
    role = await role_crud.get(db, id=role_id)
    if not role or not role.is_active:
        raise NotFoundError("角色不存在或已禁用")
    await role_crud.assign_to_user(db, user_id=user_id, role_id=role_id)
    return Response(code=200, message="分配成功")


@router.post(
    "/remove",
    response_model=Response[None],
    summary="移除用户角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def remove_role(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: int,
    role_id: int,
    current_user=Depends(get_current_superuser),
) -> Any:
    """移除用户角色"""
    user = await user_crud.get(db, id=user_id)
    if not user:
        raise NotFoundError("用户不存在")
    role = await role_crud.get(db, id=role_id)
    if not role:
        raise NotFoundError("角色不存在")
    await role_crud.remove_from_user(db, user_id=user_id, role_id=role_id)
    return Response(code=200, message="移除成功")


@router.get(
    "/user/{user_id}",
    response_model=Response[list[Role]],
    summary="获取用户的角色",
    dependencies=[Depends(log_request("admin action"))],
)
async def list_user_roles(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_superuser),
) -> Any:
    """获取用户的所有角色"""
    user = await user_crud.get(db, id=user_id)
    if not user:
        raise NotFoundError("用户不存在")
    roles = await role_crud.get_user_roles(db, user_id=user_id)
    return Response(code=200, message="获取成功", data=list(roles))
