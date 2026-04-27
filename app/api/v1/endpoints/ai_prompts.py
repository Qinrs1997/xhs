"""AI 提示词管理端点

端点：
- GET  /prompts       - 列出提示词模板
- GET  /prompts/{key} - 获取提示词详情
- DELETE /prompts/{id} - 删除提示词
- POST /prompts/preview - 预览提示词
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError, InternalError, PermissionDeniedError
from app.models.user import User
from app.ai.schemas.prompts import (
    PromptInfo,
    PromptListResponse,
    PromptDetailResponse,
    PromptPreviewRequest,
    PromptPreviewResponse,
)
from app.core.logger import logger
from app.schemas.response import Response

router = APIRouter()


@router.get(
    "/prompts",
    response_model=Response[PromptListResponse],
    summary="列出提示词模板",
    description="统一列出系统内置模板和用户自定义模板"
)
async def list_prompts(
    category: Optional[str] = Query(
        default=None,
        description="按分类过滤，如 'xhs', 'chat', 'custom'"
    ),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> PromptListResponse:
    """
    统一列出提示词模板

    合并两个来源：
    - 系统内置模板（文件系统, source=system, 只读）
    - 用户/公共模板（数据库, source=user/public, 可编辑）

    用户模板优先：如果用户创建了同 key 的模板，系统模板会被覆盖。
    """
    prompt_list: list[PromptInfo] = []
    user_keys: set[str] = set()

    # === 1. 从数据库加载用户/公共模板 ===
    try:
        from app.crud.prompt import prompt_crud

        user_prompts = await prompt_crud.get_user_prompts(
            db, user_id=current_user.id, category=category, skip=0, limit=500
        )

        for p in user_prompts:
            user_keys.add(p.key)
            if category and p.category != category:
                continue
            prompt_list.append(PromptInfo(
                id=p.id,
                key=p.key,
                name=p.name,
                description=p.description or "",
                category=p.category or "custom",
                version=p.version or "1.0.0",
                tags=p.tags or [],
                variables=list((p.variables or {}).keys()),
                source="user",
                is_readonly=False,
                created_at=p.created_at.isoformat() if p.created_at else None,
            ))

        public_prompts = await prompt_crud.get_public_prompts(db, category=category)
        for p in public_prompts:
            if p.key in user_keys:
                continue
            user_keys.add(p.key)
            prompt_list.append(PromptInfo(
                id=p.id,
                key=p.key,
                name=p.name,
                description=p.description or "",
                category=p.category or "custom",
                version=p.version or "1.0.0",
                tags=p.tags or [],
                variables=list((p.variables or {}).keys()),
                source="public",
                is_readonly=not current_user.is_superuser,
                created_at=p.created_at.isoformat() if p.created_at else None,
            ))
    except Exception as e:
        logger.warning("加载数据库提示词失败: {}", e)

    # === 2. 从文件系统加载系统模板 ===
    try:
        from app.ai.prompts import prompts as prompt_manager

        templates = prompt_manager.list_with_meta(category)

        for t in templates:
            key = t["key"]
            if key in user_keys:
                continue

            meta = t.get("meta") or {}
            variables = meta.get("variables", [])
            if isinstance(variables, dict):
                variables = list(variables.keys())
            elif not isinstance(variables, list):
                variables = []

            tpl_category = key.split("/")[0] if "/" in key else "general"
            if category and tpl_category != category:
                continue

            prompt_list.append(PromptInfo(
                id=None,
                key=key,
                name=meta.get("name", key),
                description=meta.get("description", ""),
                category=tpl_category,
                version=meta.get("version", "1.0.0"),
                tags=meta.get("tags", []),
                variables=variables,
                source="system",
                is_readonly=True,
                created_at=None,
            ))
    except Exception as e:
        logger.warning("加载文件模板失败: {}", e)

    return Response(data=PromptListResponse(prompts=prompt_list, total=len(prompt_list)))


@router.get(
    "/prompts/{prompt_key:path}",
    response_model=Response[PromptDetailResponse],
    summary="获取提示词详情",
    description="获取指定提示词的详细信息（优先数据库，其次文件）"
)
async def get_prompt_detail(
    prompt_key: str = Path(..., description="提示词 key，如 'xhs/content'"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> PromptDetailResponse:
    """
    获取提示词详情

    查找优先级：数据库（用户模板）> 文件系统（系统模板）
    """
    # 1. 先查数据库
    try:
        from app.crud.prompt import prompt_crud

        db_prompt = await prompt_crud.get_by_key(db, key=prompt_key, user_id=current_user.id)
        if not db_prompt:
            db_prompt = await prompt_crud.get_by_key(db, key=prompt_key, user_id=None)

        if db_prompt:
            content_preview = (db_prompt.content[:500] + "...") if len(db_prompt.content) > 500 else db_prompt.content
            source = "user" if db_prompt.user_id else "public"
            return Response(data=PromptDetailResponse(
                id=db_prompt.id,
                key=db_prompt.key,
                name=db_prompt.name,
                version=db_prompt.version or "1.0.0",
                description=db_prompt.description or "",
                author="",
                category=db_prompt.category or "custom",
                extends=db_prompt.extends or [],
                variables=db_prompt.variables or {},
                tags=db_prompt.tags or [],
                content_preview=content_preview,
                source=source,
                is_readonly=(source == "public" and not current_user.is_superuser),
            ))
    except Exception as e:
        logger.debug("数据库查询提示词失败: {}", e)

    # 2. 再查文件系统
    try:
        from app.ai.prompts import prompts as prompt_manager

        template = prompt_manager.get_template(prompt_key)

        if not template:
            raise NotFoundError(f"提示词 '{prompt_key}' 不存在")

        meta = template.meta
        content_preview = template.content[:500] + "..." if len(template.content) > 500 else template.content
        tpl_category = prompt_key.split("/")[0] if "/" in prompt_key else "general"

        return Response(data=PromptDetailResponse(
            id=None,
            key=prompt_key,
            name=meta.name if meta else "",
            version=meta.version if meta else "1.0.0",
            description=meta.description if meta else "",
            author=meta.author if meta else "",
            category=tpl_category,
            extends=meta.extends if meta else [],
            variables=meta.variables if meta else {},
            tags=meta.tags if meta else [],
            content_preview=content_preview,
            source="system",
            is_readonly=True,
        ))
    except NotFoundError:
        raise
    except Exception as e:
        logger.exception("获取提示词详情失败: {}", e)
        raise InternalError("获取提示词详情失败") from e


@router.delete(
    "/prompts/{prompt_id:int}",
    response_model=Response[dict],
    summary="删除提示词",
    description="删除用户自定义提示词（系统内置模板不可删除）"
)
async def delete_prompt(
    prompt_id: int = Path(..., description="提示词 ID"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """删除提示词（仅限数据库中的用户/公共模板）"""
    from app.crud.prompt import prompt_crud

    prompt = await prompt_crud.get_by_id(db, prompt_id)

    if not prompt:
        raise NotFoundError("提示词不存在")

    if prompt.user_id and prompt.user_id != current_user.id:
        raise PermissionDeniedError("无权删除此提示词")
    if prompt.user_id is None and not current_user.is_superuser:
        raise PermissionDeniedError("无权删除公共提示词")

    key, owner_id, was_public = prompt.key, prompt.user_id, prompt.is_public
    await prompt_crud.delete(db, prompt)

    # 精确失效 PromptManager 缓存(含公共维度),避免后续请求读到旧快照
    try:
        from app.ai.prompts import prompts as _pm

        _pm.invalidate(key, user_id=owner_id)
        if was_public or owner_id is None:
            _pm.invalidate(key, user_id=None)
    except Exception as _e:
        logger.warning("PromptManager 缓存失效失败(可忽略): {}", _e)

    return Response(data={"message": "提示词已删除", "id": prompt_id})


@router.post(
    "/prompts/preview",
    response_model=Response[PromptPreviewResponse],
    summary="预览提示词",
    description="使用变量渲染提示词并预览结果"
)
async def preview_prompt(
    request: PromptPreviewRequest,
    current_user: User = Depends(get_current_active_user),
) -> PromptPreviewResponse:
    """预览提示词,返回渲染后的完整内容。

    兼容三种来源(按优先级):
    1. 当前用户私有的 DB 模板
    2. 公共 DB 模板(user_id 为空或 is_public=True)
    3. 内置/自定义文件模板
    `exists_async(user_id=...)` 会检查上述所有来源;`get(user_id=...)` 会按同样顺序解析。
    这样"只存在于 DB 里的模板"和"当前用户私有覆盖"都能在预览里正确渲染。
    """
    try:
        from app.ai.prompts import prompts as prompt_manager

        if not await prompt_manager.exists_async(request.key, user_id=current_user.id):
            raise NotFoundError(f"提示词 '{request.key}' 不存在")

        rendered = await prompt_manager.get(
            request.key,
            variables=request.variables or {},
            user_id=current_user.id,
        )
        variables_used = list(request.variables.keys()) if request.variables else []
        token_count = len(rendered) // 4

        return Response(data=PromptPreviewResponse(
            key=request.key,
            rendered_content=rendered,
            variables_used=variables_used,
            token_count=token_count,
        ))
    except NotFoundError:
        raise
    except Exception as e:
        logger.exception("预览提示词失败: {}", e)
        raise InternalError("预览提示词失败") from e
