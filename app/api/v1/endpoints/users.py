"""异步用户管理 API

包含审计日志记录示例，展示如何选择性记录敏感操作。
"""
from typing import Any, Sequence
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_db
from app.api.deps import (
    get_current_active_user,
    get_current_superuser,
)
from app.core.utils import log_request
from app.core.exceptions import NotFoundError, DuplicateError, PermissionDeniedError
from app.core.audit import get_audit_logger, AuditLogger, AuditAction
from app.crud import user as user_crud
from app.schemas import (
    User,
    UserCreate,
    UserUpdate,
    Response
)
from app.schemas.user import UserWithDepartments, UserListWithDepartments, UserDepartmentInfo
from app.models.user import User as UserModel
from app.models.department import UserDepartment

router = APIRouter()


def _build_department_info(links: Sequence) -> tuple[list[UserDepartmentInfo], UserDepartmentInfo | None]:
    """
    从部门关联列表构建部门信息

    Args:
        links: UserDepartment 关联列表（需已加载 department 关系）

    Returns:
        (departments, primary_department)
    """
    departments = []
    primary_department = None

    for link in links:
        dept_info = UserDepartmentInfo(
            department_id=link.department_id,
            department_name=link.department.name if link.department else "",
            department_code=link.department.code if link.department else "",
            is_primary=link.is_primary,
            position=link.position
        )
        departments.append(dept_info)
        if link.is_primary:
            primary_department = dept_info

    return departments, primary_department


def build_user_with_departments(user: UserModel) -> UserWithDepartments:
    """
    从已预加载 department_links 的用户对象构建 UserWithDepartments

    注意：调用此函数前，需确保 user.department_links 及其 department 关系已被预加载
    """
    links = getattr(user, 'department_links', [])
    departments, primary_department = _build_department_info(links)

    return UserWithDepartments(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        avatar=user.avatar,
        bio=getattr(user, 'bio', None),
        is_active=user.is_active,
        created_at=user.created_at,
        departments=departments,
        primary_department=primary_department
    )


@router.get(
    "",
    response_model=Response[UserListWithDepartments],
    summary="获取用户列表",
    dependencies=[Depends(log_request("admin action"))],
)
async def get_users(
    db: AsyncSession = Depends(get_async_db),
    keyword: str = Query(None, description="搜索关键词（用户名/邮箱/全名）"),
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数"),
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取用户列表（支持关键词搜索，仅超级用户，包含部门信息）"""
    # 构造查询 - 使用 selectinload 预加载部门关联，避免 N+1 查询
    query = (
        select(UserModel)
        .options(
            # 预加载用户的部门关联
            selectinload(UserModel.department_links)
            # 嵌套预加载关联的部门详情
            .selectinload(UserDepartment.department)
        )
    )
    count_query = select(func.count()).select_from(UserModel)

    if keyword:
        keyword = keyword.strip()
        filter_stmt = or_(
            UserModel.username.ilike(f"%{keyword}%"),
            UserModel.email.ilike(f"%{keyword}%"),
            UserModel.full_name.ilike(f"%{keyword}%")
        )
        query = query.where(filter_stmt)
        count_query = count_query.where(filter_stmt)

    # 执行查询
    total = await db.scalar(count_query) or 0
    result = await db.execute(query.offset(skip).limit(limit))
    users = result.scalars().all()

    # 直接从预加载的数据构建响应，无需额外查询
    user_list = [build_user_with_departments(user) for user in users]

    return Response(
        code=200,
        success=True,
        message="获取成功",
        data=UserListWithDepartments(total=total, items=user_list)
    )


@router.post(
    "",
    response_model=Response[User],
    status_code=200,
    summary="创建用户",
    dependencies=[Depends(log_request("admin action"))],
)
async def create_user(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_in: UserCreate,
    current_user: UserModel = Depends(get_current_superuser),
    # 审计日志：记录用户创建操作
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_REGISTER,
        description="管理员创建用户"
    ))
) -> Any:
    """创建新用户（仅超级用户）"""
    # 检查用户名是否已存在
    user = await user_crud.get_by_username(db, username=user_in.username)
    if user:
        await audit.log(success=False, error_message="用户名已存在")
        raise DuplicateError("用户名已存在")

    # 检查邮箱是否已存在
    user = await user_crud.get_by_email(db, email=user_in.email)
    if user:
        await audit.log(success=False, error_message="邮箱已存在")
        raise DuplicateError("邮箱已存在")

    user = await user_crud.create(db, obj_in=user_in)

    # 记录审计日志（包含详情）
    await audit.log(
        detail={
            "new_user_id": user.id,
            "username": user.username,
            "email": user.email,
        }
    )

    return Response(code=200, message="创建成功", data=user)


@router.get("/get-async-routes", response_model=Response[list], summary="获取动态路由")
async def get_async_routes(
    current_user: UserModel = Depends(get_current_active_user)
) -> Any:
    """返回前端需要的路由树"""
    # 模拟路由数据，实际开发可存入数据库
    routes = [
        {
            "path": "/announcement",
            "meta": {
                "title": "公告管理",
                "icon": "ep:notification",
                "rank": 1
            },
            "children": [
                {
                    "path": "/announcement/index",
                    "name": "Announcement",
                    "meta": {
                        "title": "系统公告",
                        "roles": ["admin", "common"]
                    }
                }
            ]
        }
    ]

    # 如果是超级管理员，增加权限管理菜单
    if current_user.is_superuser:
        routes.append({
            "path": "/permission",
            "meta": {
                "title": "权限管理",
                "icon": "ep:lollipop",
                "rank": 10
            },
            "children": [
                {
                    "path": "/permission/page/index",
                    "name": "PermissionPage",
                    "meta": {
                        "title": "页面权限",
                        "roles": ["admin"]
                    }
                }
            ]
        })

    return Response(code=200, message="获取成功", data=routes)


@router.get("/me", response_model=Response[UserWithDepartments], summary="获取当前用户信息")
async def get_me(
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_active_user)
) -> Any:
    """
    获取当前登录用户信息（包含部门信息）

    注意：虽然 current_user 已包含基本用户信息，但为了获取完整的部门关联数据，
    需要使用 selectinload 重新查询。这是因为 get_current_active_user 依赖
    不会预加载部门关系，避免所有接口都承担这个开销。
    """
    # 重新查询以预加载部门关联（current_user 未包含部门关系）
    result = await db.execute(
        select(UserModel)
        .options(
            selectinload(UserModel.department_links)
            .selectinload(UserDepartment.department)
        )
        .where(UserModel.id == current_user.id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError("用户不存在")

    user_with_dept = build_user_with_departments(user)
    return Response(code=200, message="获取成功", data=user_with_dept)


@router.put("/me", response_model=Response[User], summary="更新当前用户信息")
async def update_me(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_in: UserUpdate,
    current_user: UserModel = Depends(get_current_active_user),
    # 审计日志：记录用户信息修改
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_UPDATE,
        description="用户修改个人信息"
    ))
) -> Any:
    """更新当前用户信息"""
    # 如果更新邮箱，检查是否已存在
    if user_in.email:
        existing_user = await user_crud.get_by_email(db, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            await audit.log(success=False, error_message="邮箱已存在")
            raise DuplicateError("邮箱已存在")

    user = await user_crud.update(db, db_obj=current_user, obj_in=user_in)

    # 记录审计日志
    await audit.log(
        detail={
            "updated_fields": user_in.model_dump(exclude_unset=True),
        }
    )

    return Response(code=200, message="更新成功", data=user)


@router.get(
    "/{user_id}",
    response_model=Response[UserWithDepartments],
    summary="获取指定用户",
    dependencies=[Depends(log_request("admin action"))],
)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """根据 ID 获取用户（仅超级用户，包含部门信息）"""
    # 使用预加载查询，一次性获取用户及其部门信息
    result = await db.execute(
        select(UserModel)
        .options(
            selectinload(UserModel.department_links)
            .selectinload(UserDepartment.department)
        )
        .where(UserModel.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise NotFoundError("用户不存在")

    user_with_dept = build_user_with_departments(user)
    return Response(code=200, message="获取成功", data=user_with_dept)


@router.put(
    "/{user_id}",
    response_model=Response[User],
    summary="更新指定用户",
    dependencies=[Depends(log_request("admin action"))],
)
async def update_user(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: int,
    user_in: UserUpdate,
    current_user: UserModel = Depends(get_current_superuser),
    # 审计日志：管理员修改用户
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_UPDATE,
        description="管理员修改用户信息"
    ))
) -> Any:
    """更新指定用户（仅超级用户）"""
    user = await user_crud.get(db, id=user_id)
    if not user:
        await audit.log(success=False, error_message="用户不存在")
        raise NotFoundError("用户不存在")

    # 如果更新邮箱，检查是否已存在
    if user_in.email:
        existing_user = await user_crud.get_by_email(db, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            await audit.log(success=False, error_message="邮箱已存在")
            raise DuplicateError("邮箱已存在")

    user = await user_crud.update(db, db_obj=user, obj_in=user_in)

    # 记录审计日志
    await audit.log(
        detail={
            "target_user_id": user_id,
            "updated_fields": user_in.model_dump(exclude_unset=True),
        }
    )

    return Response(code=200, message="更新成功", data=user)


@router.delete(
    "/{user_id}",
    response_model=Response[None],
    summary="删除用户",
    dependencies=[Depends(log_request("admin action"))],
)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_superuser),
    # 审计日志：高敏感操作 - 用户删除
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_DELETE,
        description="管理员删除用户"
    ))
) -> Any:
    """删除用户（仅超级用户）"""
    user = await user_crud.get(db, id=user_id)
    if not user:
        await audit.log(success=False, error_message="用户不存在")
        raise NotFoundError("用户不存在")

    # 保护逻辑：禁止删除超级管理员或名为 admin 的账户
    if user.username == "admin" or user.is_superuser:
        await audit.log(success=False, error_message="禁止删除系统管理员账户")
        raise PermissionDeniedError("禁止删除系统管理员账户，以防系统瘫痪")

    # 先记录审计日志（包含被删除用户信息）
    await audit.log(
        detail={
            "deleted_user_id": user_id,
            "deleted_username": user.username,
            "deleted_email": user.email,
        }
    )

    await user_crud.delete(db, id=user_id)
    return Response(code=200, message="删除成功")
