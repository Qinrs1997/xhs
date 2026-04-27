"""用户提示词 API 端点

提供用户和管理员的提示词增删改查功能。

端点列表:
用户端点:
- GET    /prompts/user          列出自己的提示词
- POST   /prompts/user          创建提示词
- GET    /prompts/user/{id}     获取提示词详情
- PUT    /prompts/user/{id}     更新提示词
- DELETE /prompts/user/{id}     删除提示词

管理员端点:
- GET    /prompts/admin         列出所有提示词
- POST   /prompts/admin         创建公共提示词
- PUT    /prompts/admin/{id}    更新任意提示词
- DELETE /prompts/admin/{id}    删除任意提示词
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError, PermissionDeniedError, DuplicateError
from app.models.user import User
from app.models.prompt import UserPrompt
from app.crud.prompt import prompt_crud
from app.ai.schemas.prompt_user import (
    UserPromptCreate,
    UserPromptUpdate,
    UserPromptResponse,
    UserPromptListItem,
    UserPromptListResponse,
    UserPromptCreateResponse,
)
from app.core.logger import logger

router = APIRouter()


def _invalidate_prompt_cache(key: str, user_id: Optional[int]) -> None:
    """CRUD 写操作后,精确淘汰 PromptManager 缓存,避免后续请求读到旧快照"""
    try:
        from app.ai.prompts import prompts as prompt_manager

        prompt_manager.invalidate(key, user_id=user_id)
    except Exception as e:
        logger.warning("PromptManager 缓存失效失败(可忽略): {}", e)


# ==================== 用户端点 ====================

@router.get(
    "/user",
    response_model=UserPromptListResponse,
    summary="列出我的提示词",
    description="获取当前用户可用的提示词（自己创建的 + 公共模板）"
)
async def list_my_prompts(
    category: Optional[str] = Query(default=None, description="按分类过滤"),
    skip: int = Query(default=0, ge=0, description="跳过数量"),
    limit: int = Query(default=50, ge=1, le=100, description="返回数量"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptListResponse:
    """列出当前用户可用的提示词（自己的 + 公共模板）"""
    prompts = await prompt_crud.get_available_prompts(
        db,
        user_id=current_user.id,
        category=category,
        skip=skip,
        limit=limit,
    )

    # 正确的总数:用 COUNT 查询而不是 len(已分页列表)
    count_stmt = select(func.count(UserPrompt.id)).where(
        (UserPrompt.user_id == current_user.id)
        | (UserPrompt.is_public.is_(True))
        | (UserPrompt.user_id.is_(None))
    )
    if category:
        count_stmt = count_stmt.where(UserPrompt.category == category)
    total = (await db.execute(count_stmt)).scalar() or 0

    items = [
        UserPromptListItem(
            id=p.id,
            key=p.key,
            full_key=p.full_key,
            name=p.name,
            description=p.description,
            category=p.category,
            tags=p.tags or [],
            is_public=p.is_public,
            user_id=p.user_id,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in prompts
    ]

    return UserPromptListResponse(prompts=items, total=total)


@router.post(
    "/user",
    response_model=UserPromptCreateResponse,
    summary="创建我的提示词",
    description="创建一个新的用户提示词"
)
async def create_my_prompt(
    request: UserPromptCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptCreateResponse:
    """创建用户提示词"""
    # 如果 key 为空，自动生成
    if not request.key:
        import time
        request.key = f"prompt_{int(time.time())}_{current_user.id}"

    # 检查 key 是否已存在
    if await prompt_crud.key_exists(db, request.key, user_id=current_user.id):
        raise DuplicateError(f"提示词 key '{request.key}' 已存在")

    # 普通用户不能设置 is_public(User 模型仅有 is_superuser,历史 getattr 'is_admin' 形同虚设)
    is_public = bool(request.is_public and current_user.is_superuser)

    prompt = await prompt_crud.create(
        db,
        key=request.key,
        name=request.name,
        content=request.content,
        user_id=current_user.id,
        description=request.description,
        category=request.category,
        variables=request.variables,
        extends=request.extends,
        tags=request.tags,
        is_public=is_public,
        image_config=request.image_config,
    )

    # 新建公共模板(user_id 为空或 is_public)可能影响其它用户的读取,清缓存
    if prompt.is_public or prompt.user_id is None:
        _invalidate_prompt_cache(prompt.key, user_id=None)
    _invalidate_prompt_cache(prompt.key, user_id=current_user.id)

    return UserPromptCreateResponse(
        id=prompt.id,
        key=prompt.key,
        full_key=prompt.full_key,
        name=prompt.name,
        category=prompt.category,
        created_at=prompt.created_at.isoformat(),
    )


@router.get(
    "/user/{prompt_id}",
    response_model=UserPromptResponse,
    summary="获取我的提示词详情",
    description="获取指定提示词的详细信息"
)
async def get_my_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptResponse:
    """获取用户提示词详情"""
    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    # 检查权限：只能查看自己的或公共的
    if prompt.user_id != current_user.id and not prompt.is_public and prompt.user_id is not None:
        raise PermissionDeniedError("无权访问此提示词")

    return UserPromptResponse(**prompt.to_dict())


@router.put(
    "/user/{prompt_id}",
    response_model=UserPromptResponse,
    summary="更新我的提示词",
    description="更新指定的提示词"
)
async def update_my_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    request: UserPromptUpdate = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptResponse:
    """更新用户提示词"""
    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    # 只能更新自己的
    if prompt.user_id != current_user.id:
        raise PermissionDeniedError("无权修改此提示词")

    # 普通用户不能修改 is_public(改为 None 表示忽略传入值)
    is_public = request.is_public
    if is_public is not None and not current_user.is_superuser:
        is_public = None

    prompt = await prompt_crud.update(
        db,
        prompt,
        name=request.name,
        description=request.description,
        content=request.content,
        category=request.category,
        variables=request.variables,
        extends=request.extends,
        tags=request.tags,
        is_public=is_public,
        image_config=request.image_config,
    )
    _invalidate_prompt_cache(prompt.key, user_id=prompt.user_id)
    if prompt.is_public or prompt.user_id is None:
        _invalidate_prompt_cache(prompt.key, user_id=None)

    return UserPromptResponse(**prompt.to_dict())


@router.delete(
    "/user/{prompt_id}",
    summary="删除我的提示词",
    description="删除指定的提示词"
)
async def delete_my_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """删除用户提示词"""
    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    if prompt.user_id != current_user.id:
        raise PermissionDeniedError("无权删除此提示词")

    key, owner_id, was_public = prompt.key, prompt.user_id, prompt.is_public
    await prompt_crud.delete(db, prompt)
    _invalidate_prompt_cache(key, user_id=owner_id)
    if was_public or owner_id is None:
        _invalidate_prompt_cache(key, user_id=None)

    return {"message": "提示词已删除", "id": prompt_id}


# ==================== 管理员端点 ====================

@router.get(
    "/admin",
    response_model=UserPromptListResponse,
    summary="[管理员] 列出所有提示词",
    description="管理员查看所有用户的提示词"
)
async def admin_list_prompts(
    category: Optional[str] = Query(default=None, description="按分类过滤"),
    user_id: Optional[int] = Query(default=None, description="按用户过滤"),
    skip: int = Query(default=0, ge=0, description="跳过数量"),
    limit: int = Query(default=50, ge=1, le=100, description="返回数量"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptListResponse:
    """管理员列出所有提示词"""

    if user_id:
        prompts = await prompt_crud.get_user_prompts(
            db, user_id=user_id, category=category, skip=skip, limit=limit
        )
    else:
        prompts = await prompt_crud.get_all_prompts(
            db, category=category, skip=skip, limit=limit
        )

    items = [
        UserPromptListItem(
            id=p.id,
            key=p.key,
            full_key=p.full_key,
            name=p.name,
            description=p.description,
            category=p.category,
            tags=p.tags or [],
            is_public=p.is_public,
            user_id=p.user_id,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in prompts
    ]

    return UserPromptListResponse(prompts=items, total=len(items))


@router.post(
    "/admin",
    response_model=UserPromptCreateResponse,
    summary="[管理员] 创建公共提示词",
    description="管理员创建公共/系统级提示词"
)
async def admin_create_prompt(
    request: UserPromptCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptCreateResponse:
    """管理员创建公共提示词"""
    # 检查公共 key 是否已存在
    if await prompt_crud.key_exists(db, request.key, user_id=None):
        raise DuplicateError(f"公共提示词 key '{request.key}' 已存在")

    # 管理员创建的默认为公共模板（user_id=None）
    prompt = await prompt_crud.create(
        db,
        key=request.key,
        name=request.name,
        content=request.content,
        user_id=None,  # 公共模板
        description=request.description,
        category=request.category,
        variables=request.variables,
        extends=request.extends,
        tags=request.tags,
        is_public=True,
        image_config=request.image_config,
    )
    _invalidate_prompt_cache(prompt.key, user_id=None)

    return UserPromptCreateResponse(
        id=prompt.id,
        key=prompt.key,
        full_key=prompt.full_key,
        name=prompt.name,
        category=prompt.category,
        created_at=prompt.created_at.isoformat(),
    )


@router.put(
    "/admin/{prompt_id}",
    response_model=UserPromptResponse,
    summary="[管理员] 更新任意提示词",
    description="管理员更新任意用户的提示词"
)
async def admin_update_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    request: UserPromptUpdate = None,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_db),
) -> UserPromptResponse:
    """管理员更新提示词"""
    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    prompt = await prompt_crud.update(
        db,
        prompt,
        name=request.name,
        description=request.description,
        content=request.content,
        category=request.category,
        variables=request.variables,
        extends=request.extends,
        tags=request.tags,
        is_public=request.is_public,
        image_config=request.image_config,
    )
    _invalidate_prompt_cache(prompt.key, user_id=prompt.user_id)
    if prompt.is_public or prompt.user_id is None:
        _invalidate_prompt_cache(prompt.key, user_id=None)

    return UserPromptResponse(**prompt.to_dict())


@router.delete(
    "/admin/{prompt_id}",
    summary="[管理员] 删除任意提示词",
    description="管理员删除任意提示词"
)
async def admin_delete_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_db),
):
    """管理员删除提示词"""
    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    key, owner_id, was_public = prompt.key, prompt.user_id, prompt.is_public
    await prompt_crud.delete(db, prompt)
    _invalidate_prompt_cache(key, user_id=owner_id)
    if was_public or owner_id is None:
        _invalidate_prompt_cache(key, user_id=None)

    return {"message": "提示词已删除", "id": prompt_id}
