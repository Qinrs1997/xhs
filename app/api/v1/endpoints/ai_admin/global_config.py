"""AI 全局配置 GET / PATCH 接口

通过 AISettings 表持久化 AI 功能开关和默认参数。
"""
import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_superuser
from app.core.database import get_async_db
from app.core.logger import logger
from app.models.ai import AISettings
from app.models.user import User
from app.schemas.ai_admin import (
    DEFAULT_AI_GLOBAL_CONFIG,
    AIGlobalConfigResponse,
    AIGlobalConfigUpdate,
)
from app.schemas.response import Response

router = APIRouter()


@router.get(
    "/config",
    response_model=Response[AIGlobalConfigResponse],
    summary="获取全局 AI 配置",
)
async def get_global_config(
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_active_user),
):
    """获取全局 AI 配置

    返回当前生效的所有 AI 功能开关和限制配置。
    前端可根据 enabled 字段决定是否显示 AI 界面。
    """
    result = await db.execute(select(AISettings).where(AISettings.key == "global_config"))
    setting = result.scalar_one_or_none()

    config = json.loads(setting.value) if setting else DEFAULT_AI_GLOBAL_CONFIG.copy()

    return Response(
        message="获取成功",
        data=AIGlobalConfigResponse(
            config=config,
            source="database" if setting else "default",
        ),
    )


@router.patch(
    "/config",
    response_model=Response[AIGlobalConfigResponse],
    summary="修改全局 AI 配置",
)
async def update_global_config(
    data: AIGlobalConfigUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_superuser),
):
    """修改全局 AI 配置

    管理员可以通过此接口：
    - 开启/关闭 AI 功能（关闭后前端不显示 AI 界面）
    - 开启/关闭特定功能（聊天、总结、搜索等）
    - 设置使用限制（Token 上限、每日请求数）
    """
    result = await db.execute(select(AISettings).where(AISettings.key == "global_config"))
    setting = result.scalar_one_or_none()

    current_config = (
        json.loads(setting.value) if setting else DEFAULT_AI_GLOBAL_CONFIG.copy()
    )

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        current_config[key] = value

    if setting:
        setting.value = json.dumps(current_config)
        setting.updated_by = current_user.id
    else:
        setting = AISettings(
            key="global_config",
            value=json.dumps(current_config),
            description="AI 全局配置",
            updated_by=current_user.id,
        )
        db.add(setting)

    await db.commit()

    logger.info("管理员 {} 更新了 AI 全局配置: {}", current_user.username, update_data)

    return Response(
        message="配置已更新",
        data=AIGlobalConfigResponse(config=current_config, source="database"),
    )
