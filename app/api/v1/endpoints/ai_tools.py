"""AI 工具端点（健康检查 + 统计 + 配置）

端点列表：
- GET  /health   - 健康检查
- GET  /stats    - 统计信息
- GET  /config   - 配置信息
"""
import time
import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.database import get_async_db
from app.core.exceptions import InternalError
from app.models.user import User
from app.schemas.response import Response
from app.ai.facade import ai
from app.ai.config import ai_config
from app.ai.exceptions import AIError
from app.core.logger import logger

router = APIRouter()


# ==================== 工具端点 ====================

@router.get(
    "/health",
    response_model=Response[dict],
    summary="AI 健康检查",
    description="检查 AI 服务是否正常运行"
)
async def ai_health_check():
    """AI 健康检查"""
    if not ai_config.enabled:
        return Response(data={
            "status": "error",
            "provider": ai_config.default_provider,
            "latency_ms": 0,
            "error": "AI 服务未启用",
        })

    try:
        start = time.perf_counter()
        health = await ai.health_check()
        latency_ms = int((time.perf_counter() - start) * 1000)

        # 安全处理空值
        health = health or {}
        provider = health.get("provider", ai_config.default_provider)
        provider_healthy = health.get("provider_healthy", False)
        status = "success" if provider_healthy else "error"

        response = {
            "status": status,
            "provider": provider,
            "latency_ms": latency_ms,
        }
        if health.get("error"):
            response["error"] = health["error"]
        return Response(data=response)
    except Exception as e:
        logger.exception("AI 健康检查异常: {}", e)
        return Response(data={
            "status": "error",
            "provider": ai_config.default_provider,
            "latency_ms": 0,
            "error": str(e),
        })


@router.get(
    "/stats",
    response_model=Response[dict],
    summary="AI 统计信息",
    description="获取 AI 服务的统计信息"
)
async def ai_stats(
    current_user: User = Depends(get_current_active_user),
):
    """AI 统计信息"""
    try:
        stats = ai.get_stats()
        return Response(data=stats)
    except AIError as e:
        raise InternalError(e.message) from e


@router.get(
    "/config",
    response_model=Response[dict],
    summary="AI 配置信息",
    description="获取 AI 服务的配置信息（包含动态开关状态，用于前端判断是否显示 AI 界面）"
)
async def ai_config_info(
    db: AsyncSession = Depends(get_async_db)
):
    """
    获取 AI 配置（脱敏）

    前端应根据返回的 `enabled` 字段决定是否显示 AI 相关界面。
    """
    from app.models.ai import AISettings
    from sqlalchemy import select

    # 默认配置
    global_config = {
        "enabled": True,
        "chat_enabled": True,
        "summary_enabled": True,
        "search_enabled": False,
        "image_enabled": False,
        "data_analysis_enabled": False,
    }

    # 尝试从数据库加载动态配置
    try:
        result = await db.execute(select(AISettings).where(AISettings.key == "global_config"))
        setting = result.scalar_one_or_none()
        if setting:
            db_config = json.loads(setting.value)
            global_config.update(db_config)
    except Exception as e:
        # 数据库异常时使用默认配置（不阻断接口返回）
        logger.warning("读取 AI 动态配置失败，回退到默认值: {}", e)

    from app.ai.services.dynamic_config import get_dynamic_config

    dyn_config = await get_dynamic_config()
    enabled = global_config.get("enabled", True)
    chat_enabled = global_config.get("chat_enabled", True)
    summary_enabled = global_config.get("summary_enabled", True)
    search_enabled = global_config.get("search_enabled", False)

    provider = dyn_config.provider_type or ai_config.default_provider
    default_model = dyn_config.default_model or ai_config.openai.chat_model
    available_models = dyn_config.available_models or ai_config.openai.available_models or []

    return Response(data={
        # 需求文档字段
        "enabled": enabled,
        "provider": provider,
        "default_model": default_model,
        "available_models": available_models,
        "features": {
            "chat": enabled and chat_enabled,
            "stream": enabled and chat_enabled,
            "search": enabled and search_enabled,
            "summary": enabled and summary_enabled,
        },

        # 兼容字段（保留历史返回）
        "chat_enabled": chat_enabled,
        "summary_enabled": summary_enabled,
        "search_enabled": search_enabled,
        "image_enabled": global_config.get("image_enabled", False),
        "data_analysis_enabled": global_config.get("data_analysis_enabled", False),
        "default_provider": ai_config.default_provider,
        "openai": {
            "base_url": ai_config.openai.base_url,
            "chat_model": ai_config.openai.chat_model,
            "summary_model": ai_config.openai.summary_model,
            "available_models": ai_config.openai.available_models,
            "default_temperature": ai_config.openai.default_temperature,
            "default_max_tokens": ai_config.openai.default_max_tokens,
        },
        "context": {
            "max_messages": ai_config.context.max_messages,
            "max_tokens": ai_config.context.max_tokens,
            "storage_type": ai_config.context.storage_type,
        },
    })
