"""AI 配置热重载接口

POST /reload-config —— 从数据库重新加载 AI 服务商配置，无需重启服务。
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_active_user
from app.core.logger import logger
from app.models.user import User
from app.schemas.ai_admin import ReloadConfigResponse
from app.schemas.response import Response

router = APIRouter()


@router.post(
    "/reload-config",
    response_model=Response[ReloadConfigResponse],
    summary="热重载 AI 配置",
)
async def reload_config(_: User = Depends(get_current_active_user)):
    """热重载 AI 配置

    从数据库重新加载 AI 服务商配置，无需重启服务。
    配置变更后立即生效。
    """
    from app.ai.services.dynamic_config import reload_ai_config

    try:
        from app.ai.services.config_sync import config_sync_service
        await config_sync_service.sync_toml_to_db()
    except Exception as e:
        logger.warning("热重载时 TOML→DB 同步失败: {}", e)

    new_config = await reload_ai_config()

    try:
        from app.ai.providers.openai import OpenAIProvider
        provider = OpenAIProvider()
        await provider.refresh_client()
    except Exception as e:
        logger.warning("刷新 Provider 客户端失败: {}", e)

    return Response(
        message="配置已热重载",
        data=ReloadConfigResponse(
            message="配置已热重载",
            current_config={
                "name": new_config.name,
                "source": new_config.source,
                "base_url": new_config.base_url,
                "default_model": new_config.default_model,
            },
        ),
    )
