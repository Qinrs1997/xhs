"""AI 服务商管理接口（CRUD + 设置默认）

所有接口仅超级管理员可用。每次写操作后会使动态 AI 配置缓存失效。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superuser
from app.core.database import get_async_db
from app.core.exceptions import DuplicateError
from app.core.logger import logger
from app.models.ai import AIProvider
from app.models.user import User
from app.schemas.ai_admin import (
    AIProviderCreate,
    AIProviderResponse,
    AIProviderUpdate,
)
from app.schemas.response import Response

from ._helpers import (
    build_provider_response,
    clear_default_for_service_type,
    get_provider_or_404,
    invalidate_ai_config,
    resolve_service_type,
)

router = APIRouter()


@router.get(
    "/providers",
    response_model=list[AIProviderResponse],
    summary="获取所有 AI 服务商配置",
)
async def list_providers(
    service_type: str | None = Query(None, description="按服务类型过滤: llm|image|search"),
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """列出所有 AI 服务商配置（支持按 service_type 过滤）"""
    query = select(AIProvider)
    if service_type:
        query = query.where(AIProvider.service_type == service_type)
    query = query.order_by(AIProvider.priority.desc())
    result = await db.execute(query)
    providers = result.scalars().all()

    return [build_provider_response(p) for p in providers]


@router.post(
    "/providers",
    response_model=AIProviderResponse,
    summary="创建 AI 服务商配置",
)
async def create_provider(
    data: AIProviderCreate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """创建新的 AI 服务商配置"""
    existing = await db.execute(select(AIProvider).where(AIProvider.name == data.name))
    if existing.scalar_one_or_none():
        raise DuplicateError("服务商名称已存在")

    if data.is_default:
        await clear_default_for_service_type(db, data.service_type)

    provider = AIProvider(
        name=data.name,
        provider_type=data.provider_type,
        service_type=data.service_type,
        api_key=data.api_key,
        base_url=data.base_url,
        default_model=data.default_model,
        available_models={"models": data.available_models} if data.available_models else None,
        timeout=data.timeout,
        max_retries=data.max_retries,
        max_tokens=data.max_tokens,
        priority=data.priority,
        is_active=data.is_active,
        is_default=data.is_default,
        description=data.description,
        extra_config=data.extra_config,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info("管理员创建 AI 服务商配置: {}", data.name)
    invalidate_ai_config()

    return build_provider_response(provider, available_models_override=data.available_models)


@router.put(
    "/providers/{provider_id}",
    response_model=AIProviderResponse,
    summary="更新 AI 服务商配置",
)
async def update_provider(
    provider_id: int,
    data: AIProviderUpdate,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """更新 AI 服务商配置"""
    provider = await get_provider_or_404(db, provider_id)

    if data.is_default:
        svc_type = resolve_service_type(provider, override=data.service_type)
        await clear_default_for_service_type(db, svc_type)

    update_data = data.model_dump(exclude_unset=True)
    if not update_data.get("api_key"):
        update_data.pop("api_key", None)
    if update_data.get("available_models"):
        update_data["available_models"] = {"models": update_data["available_models"]}

    for key, value in update_data.items():
        setattr(provider, key, value)

    await db.commit()
    await db.refresh(provider)

    logger.info("管理员更新 AI 服务商配置: {}", provider.name)
    invalidate_ai_config()

    return build_provider_response(provider)


@router.delete(
    "/providers/{provider_id}",
    summary="删除 AI 服务商配置",
)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """删除 AI 服务商配置"""
    provider = await get_provider_or_404(db, provider_id)

    await db.delete(provider)
    await db.commit()

    logger.info("管理员删除 AI 服务商配置: {}", provider.name)
    invalidate_ai_config()

    return Response(message="删除成功")


@router.post(
    "/providers/{provider_id}/set-default",
    summary="设置默认服务商",
)
async def set_default_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """设置默认 AI 服务商（同 service_type 内互斥）"""
    provider = await get_provider_or_404(db, provider_id)

    svc_type = resolve_service_type(provider)
    await clear_default_for_service_type(db, svc_type)

    provider.is_default = True
    await db.commit()

    logger.info("管理员设置默认 AI 服务商: {} (type={})", provider.name, svc_type)
    invalidate_ai_config()

    return Response(message=f"已将 {provider.name} 设为 {svc_type} 默认服务商")
