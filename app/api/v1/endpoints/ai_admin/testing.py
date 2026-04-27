"""AI 服务商连通性测试接口

POST /providers/{id}/test —— 按 service_type(llm/image/search) 不同策略发起 HTTP 请求，
返回延迟和模型数量/错误信息。
"""
import time

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superuser
from app.core.database import get_async_db
from app.models.ai import AIProvider
from app.models.user import User
from app.schemas.ai_admin import ProviderTestResponse
from app.schemas.response import Response

from ._helpers import get_provider_or_404, resolve_service_type

router = APIRouter()

_TEST_TIMEOUT_SECONDS = 15


async def _test_llm(
    client: httpx.AsyncClient, provider: AIProvider, start: float
) -> ProviderTestResponse:
    """LLM 服务：GET {base_url}/models 获取模型列表"""
    response = await client.get(
        f"{provider.base_url}/models",
        headers={"Authorization": f"Bearer {provider.api_key}"},
    )
    latency = int((time.time() - start) * 1000)
    if response.status_code == 200:
        models = response.json().get("data", [])
        return ProviderTestResponse(
            status="success",
            provider=provider.name,
            latency_ms=latency,
            model_count=len(models),
        )
    return ProviderTestResponse(
        status="error",
        provider=provider.name,
        latency_ms=latency,
        error=f"HTTP {response.status_code}: {response.text[:200]}",
    )


async def _test_image(
    client: httpx.AsyncClient, provider: AIProvider, start: float
) -> ProviderTestResponse:
    """图片引擎：尝试 GET /models，失败时 GET base_url 兜底"""
    try:
        response = await client.get(
            f"{provider.base_url}/models",
            headers={"Authorization": f"Bearer {provider.api_key}"},
        )
    except Exception:
        # 某些图片 API 没有 /models，尝试 ping base_url
        response = await client.get(provider.base_url)

    latency = int((time.time() - start) * 1000)
    ok = response.status_code < 500
    return ProviderTestResponse(
        status="success" if ok else "error",
        provider=provider.name,
        latency_ms=latency,
        error=None if ok else f"HTTP {response.status_code}",
    )


async def _test_search(
    client: httpx.AsyncClient, provider: AIProvider, start: float
) -> ProviderTestResponse:
    """搜索引擎：POST /search 发一个简单查询测试连通性"""
    response = await client.post(
        f"{provider.base_url}/search",
        headers={"Authorization": f"Bearer {provider.api_key}"},
        json={"query": "test", "max_results": 1},
    )
    latency = int((time.time() - start) * 1000)
    ok = response.status_code == 200
    return ProviderTestResponse(
        status="success" if ok else "error",
        provider=provider.name,
        latency_ms=latency,
        error=None if ok else f"HTTP {response.status_code}: {response.text[:200]}",
    )


async def _test_unknown(
    client: httpx.AsyncClient, provider: AIProvider, start: float
) -> ProviderTestResponse:
    """未知 service_type：仅 ping base_url"""
    response = await client.get(provider.base_url)
    latency = int((time.time() - start) * 1000)
    ok = response.status_code < 500
    return ProviderTestResponse(
        status="success" if ok else "error",
        provider=provider.name,
        latency_ms=latency,
    )


_DISPATCH = {
    "llm": _test_llm,
    "image": _test_image,
    "search": _test_search,
}


@router.post(
    "/providers/{provider_id}/test",
    response_model=Response[ProviderTestResponse],
    summary="测试服务商连接",
)
async def test_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_superuser),
):
    """测试 AI 服务商连接是否正常（支持 LLM/图片/搜索引擎）"""
    provider = await get_provider_or_404(db, provider_id)
    svc_type = resolve_service_type(provider)
    handler = _DISPATCH.get(svc_type, _test_unknown)

    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=_TEST_TIMEOUT_SECONDS, trust_env=False) as client:
            data = await handler(client, provider, start)
        message = "连接成功" if data.status == "success" else "连接失败"
        return Response(message=message, data=data)
    except Exception as e:
        return Response(
            message="连接失败",
            data=ProviderTestResponse(
                status="error",
                provider=provider.name,
                latency_ms=0,
                error=str(e),
            ),
        )
