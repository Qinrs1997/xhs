"""AI 搜索 · API Key 在线管理

- GET   /admin/ai/search/tavily   返回当前 Tavily Key 的配置状态（掩码展示）
- PATCH /admin/ai/search/tavily   在线更新 Tavily API Key（同时写 DB + 内存，无需重启）
- POST  /admin/ai/search/tavily/test  发一个最小化搜索请求，校验 key 是否可用

业务目标：让运营/管理员可以在前端直接输入 tavily 密钥，即时生效，无需改 .env 重启。
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superuser
from app.core.database import get_async_db
from app.core.exceptions import BadRequestError
from app.core.logger import logger
from app.models.ai import AIProvider
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()


# ==================== Schema ====================

class TavilyKeyStatus(BaseModel):
    """Tavily Key 状态视图（掩码形式，绝不回显完整 key）"""
    model_config = ConfigDict(from_attributes=True)

    configured: bool = Field(..., description="是否已配置有效 Key")
    masked_key: Optional[str] = Field(None, description="掩码 Key, 形如 tvly-****abcd")
    provider: str = Field("tavily", description="搜索提供方")
    source: str = Field(..., description="来源: db / env / none")
    key_length: int = Field(0, description="Key 字符长度（辅助识别假 key）")


class TavilyKeyUpdate(BaseModel):
    """在线更新 Key 请求"""
    api_key: str = Field(..., min_length=8, max_length=200, description="Tavily API Key，必须以 tvly- 开头")


class TavilyTestResult(BaseModel):
    """Test 结果"""
    ok: bool
    results: int = 0
    latency_ms: int = 0
    error: Optional[str] = None


# ==================== 工具函数 ====================

def _mask_key(key: str | None) -> Optional[str]:
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:5]}****{key[-4:]}"


def _current_source() -> str:
    """判断当前 in-memory ai_config.search.api_key 的来源。"""
    from app.ai.config import ai_config
    import os

    env_key = os.getenv("TAVILY_API_KEY", "")
    if ai_config.search.api_key and env_key and ai_config.search.api_key == env_key:
        return "env"
    if ai_config.search.api_key:
        return "db"
    return "none"


async def _get_default_search_provider(db: AsyncSession) -> Optional[AIProvider]:
    stmt = (
        select(AIProvider)
        .where(AIProvider.service_type == "search")
        .order_by(AIProvider.is_default.desc(), AIProvider.priority.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ==================== 端点 ====================

@router.get(
    "/search/tavily",
    response_model=Response[TavilyKeyStatus],
    summary="查询 Tavily Key 配置状态（掩码）",
)
async def get_tavily_status(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
) -> Any:
    from app.ai.config import ai_config

    key = ai_config.search.api_key or ""
    return Response(
        code=200, success=True, message="ok",
        data=TavilyKeyStatus(
            configured=bool(key) and not key.startswith("sk-placeholder"),
            masked_key=_mask_key(key),
            provider="tavily",
            source=_current_source(),
            key_length=len(key),
        ),
    )


@router.patch(
    "/search/tavily",
    response_model=Response[TavilyKeyStatus],
    summary="在线更新 Tavily API Key (DB + 内存)",
)
async def update_tavily_key(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    payload: TavilyKeyUpdate,
) -> Any:
    from app.ai.config import ai_config

    new_key = payload.api_key.strip()
    if not new_key.startswith("tvly-"):
        raise BadRequestError("Tavily API Key 需以 tvly- 开头")

    # 1) 更新 DB: service_type=search 的默认 Provider
    provider = await _get_default_search_provider(db)
    if provider is None:
        # 没有默认行则新建
        from app.ai.config import ai_config as _cfg
        provider = AIProvider(
            name="Tavily 搜索",
            provider_type="search",
            service_type="search",
            api_key=new_key,
            base_url="https://api.tavily.com",
            default_model="tavily",
            available_models={"models": ["tavily", "duckduckgo", "serper", "searxng"]},
            timeout=_cfg.search.timeout,
            max_retries=3,
            max_tokens=0,
            is_active=True,
            is_default=True,
            priority=100,
            description="由管理端在线设置的 Tavily Key",
            extra_config={
                "search_provider": "tavily",
                "providers_fallback": ["tavily", "duckduckgo", "searxng"],
            },
        )
        db.add(provider)
    else:
        provider.api_key = new_key
        provider.is_active = True
        if provider.default_model not in ("tavily", None, ""):
            # 不强改用户既有选项，但记录下 key 更新
            pass
        db.add(provider)
    await db.commit()
    await db.refresh(provider)

    # 2) 更新 in-memory ai_config，让正在运行的请求立即生效（无需重启）
    ai_config.search.api_key = new_key
    # 确保开关也打开
    if hasattr(ai_config, "search_enabled"):
        ai_config.search_enabled = True

    # 3) 失效 DynamicConfig 缓存（如后续有按 service_type=search 读的地方）
    try:
        from app.ai.services.dynamic_config import dynamic_config_service
        dynamic_config_service.invalidate("search")
    except Exception as e:
        logger.warning("invalidate search dynamic config failed: {}", e)

    logger.info(
        "[ADMIN] Tavily API Key 已在线更新: masked={} by user_id={}",
        _mask_key(new_key), _admin.id,
    )

    return Response(
        code=200, success=True, message="已更新并即时生效",
        data=TavilyKeyStatus(
            configured=True,
            masked_key=_mask_key(new_key),
            provider="tavily",
            source="db",
            key_length=len(new_key),
        ),
    )


@router.post(
    "/search/tavily/test",
    response_model=Response[TavilyTestResult],
    summary="用当前 Tavily Key 发一次最小搜索 (self-test)",
)
async def test_tavily_key(
    *,
    _admin: User = Depends(get_current_superuser),
) -> Any:
    import time

    from app.ai.services.search.providers.tavily import TavilyProvider

    t0 = time.time()
    try:
        provider = TavilyProvider()
        # 直接 reload 一次 api_key,避免老实例里缓存
        from app.ai.config import ai_config
        provider.api_key = ai_config.search.api_key

        results = await provider.search(query="ping", max_results=1, search_depth="basic")
        return Response(
            code=200, success=True, message="ok",
            data=TavilyTestResult(
                ok=True,
                results=len(results),
                latency_ms=int((time.time() - t0) * 1000),
            ),
        )
    except Exception as e:
        return Response(
            code=200, success=True, message="test failed",
            data=TavilyTestResult(
                ok=False,
                results=0,
                latency_ms=int((time.time() - t0) * 1000),
                error=str(e)[:400],
            ),
        )
