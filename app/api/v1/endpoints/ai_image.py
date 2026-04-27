"""AI image endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.ai.config import ai_config
from app.ai.exceptions import AIError
from app.ai.facade import ai
from app.ai.schemas.image import ImageRequest, ImageResponse
from app.api.deps import get_current_active_user
from app.core.exceptions import InternalError, ServiceUnavailableError
from app.core.logger import logger
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()


async def _ensure_image_generation_available() -> None:
    if ai_config.image_enabled:
        return

    from app.ai.services.dynamic_config import get_dynamic_config

    dyn_config = await get_dynamic_config(service_type="image")
    if not dyn_config.base_url or not dyn_config.api_key:
        raise ServiceUnavailableError("图片生成功能未启用")


@router.get(
    "/image/models",
    response_model=Response[dict],
    summary="获取可用图片模型列表",
)
async def list_image_models(
    current_user: User = Depends(get_current_active_user),
):
    """Return image model metadata used by the frontend selector."""
    del current_user
    try:
        return Response(data=ai.get_image_models())
    except AIError as exc:
        logger.error("Failed to list image models: {}", exc)
        raise InternalError(exc.message) from exc
    except Exception as exc:
        logger.exception("Unexpected error while listing image models: {}", exc)
        raise InternalError("获取图片模型列表失败") from exc


@router.post(
    "/image/generate",
    response_model=Response[ImageResponse],
    summary="生成图片",
)
async def generate_image(
    request: ImageRequest,
    current_user: User = Depends(get_current_active_user),
    _: None = Depends(rate_limit(requests_per_minute=10)),
) -> ImageResponse:
    """Generate images from a text prompt."""
    await _ensure_image_generation_available()

    try:
        response = await ai.image_generate(
            prompt=request.prompt,
            model=request.model,
            size=request.size,
            quality=request.quality,
            style=request.style,
            n=request.n,
            negative_prompt=request.negative_prompt,
            image=request.image,
            extra_params=request.extra_params,
            user_id=current_user.id,
        )
        return Response(data=response)
    except AIError as exc:
        logger.error("Image generation failed: {}", exc)
        raise InternalError(exc.message) from exc
    except Exception as exc:
        logger.exception("Unexpected image generation error: {}", exc)
        raise InternalError("图片生成服务异常") from exc
