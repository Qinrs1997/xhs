"""ai_admin 子包内部共享工具

仅限 ai_admin 子包内部使用，不作为对外 API。
"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.ai import AIProvider
from app.schemas.ai_admin import AIProviderResponse


def format_api_key_preview(api_key: str) -> str:
    """把 API key 脱敏为 `xxxx****yyyy` 形式"""
    if len(api_key) > 8:
        return f"{api_key[:4]}****{api_key[-4:]}"
    return "****"


def resolve_service_type(provider: AIProvider, override: str | None = None) -> str:
    """返回 provider 的 service_type（空值兜底到 'llm'，兼容老数据）

    - override 优先于 provider.service_type（update 时前端传来的新值）
    - 兼容老 schema 可能缺 service_type 字段
    """
    return override or getattr(provider, "service_type", "llm") or "llm"


def build_provider_response(
    provider: AIProvider,
    *,
    available_models_override: list[str] | None = None,
) -> AIProviderResponse:
    """把 ORM AIProvider 对象转成 AIProviderResponse。

    - available_models_override: 创建/更新时前端直接传来的 list，不从 DB jsonb 取
    """
    if available_models_override is not None:
        available_models = available_models_override
    elif provider.available_models:
        available_models = provider.available_models.get("models")
    else:
        available_models = None

    return AIProviderResponse(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        service_type=resolve_service_type(provider),
        base_url=provider.base_url,
        default_model=provider.default_model,
        available_models=available_models,
        timeout=provider.timeout,
        max_retries=provider.max_retries,
        max_tokens=provider.max_tokens,
        is_active=provider.is_active,
        is_default=provider.is_default,
        priority=provider.priority,
        description=provider.description,
        api_key_preview=format_api_key_preview(provider.api_key),
        extra_config=getattr(provider, "extra_config", None),
    )


async def get_provider_or_404(db: AsyncSession, provider_id: int) -> AIProvider:
    """按 id 取 AIProvider；找不到抛 NotFoundError（返回 404）"""
    result = await db.execute(select(AIProvider).where(AIProvider.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise NotFoundError("服务商配置不存在")
    return provider


async def clear_default_for_service_type(db: AsyncSession, service_type: str) -> None:
    """把同一 service_type 下所有 provider 的 is_default 清零

    用于"设置新默认 provider"前的互斥操作。**不 commit**，由调用方统一 commit。
    """
    await db.execute(
        update(AIProvider)
        .where(AIProvider.service_type == service_type)
        .values(is_default=False)
    )


def invalidate_ai_config() -> None:
    """使动态 AI 配置缓存失效，下次请求重新加载。

    独立为函数便于单测 mock，且避免在每个接口里重复 import。
    """
    from app.ai.services.dynamic_config import dynamic_config_service
    dynamic_config_service.invalidate()
