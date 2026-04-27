"""Image generation service."""

from __future__ import annotations

from typing import Optional

from app.ai.config import ai_config
from app.ai.providers.base import BaseProvider
from app.ai.schemas.common import AIMetadata
from app.ai.schemas.image import (
    ImageData,
    ImageModelInfo,
    ImageModelsResponse,
    ImageRequest,
    ImageResponse,
)
from app.ai.services.dynamic_config import get_dynamic_config
from app.core.logger import logger


MODEL_DEFAULTS: dict[str, dict] = {
    "black-forest-labs/FLUX.1-schnell": {
        "name": "FLUX.1 Schnell",
        "default_size": "1024x1024",
        "available_sizes": [
            "1024x1024",
            "1024x1792",
            "1792x1024",
            "512x512",
            "768x512",
            "512x768",
        ],
        "supports_negative_prompt": True,
        "supports_image_edit": False,
    },
    "black-forest-labs/FLUX.1-dev": {
        "name": "FLUX.1 Dev",
        "default_size": "1024x1024",
        "available_sizes": [
            "1024x1024",
            "1024x1792",
            "1792x1024",
            "512x512",
            "768x512",
            "512x768",
        ],
        "supports_negative_prompt": True,
        "supports_image_edit": False,
        "default_extra": {"num_inference_steps": 20},
    },
    "Qwen/Qwen-Image-Edit-2509": {
        "name": "Qwen Image Edit",
        "default_size": None,
        "available_sizes": [],
        "supports_negative_prompt": False,
        "supports_image_edit": True,
        "default_extra": {"cfg": 4.0, "num_inference_steps": 50},
    },
    "Kwai-Kolors/Kolors": {
        "name": "Kolors",
        "default_size": "1024x1024",
        "available_sizes": [
            "1024x1024",
            "960x1280",
            "1280x960",
            "768x1024",
            "1024x768",
            "720x1440",
            "1440x720",
            "720x1280",
            "1280x720",
        ],
        "supports_negative_prompt": True,
        "supports_image_edit": False,
        "default_extra": {"guidance_scale": 7.5, "num_inference_steps": 25},
    },
    "gpt-image-2": {
        "name": "APIMart GPT-Image-2",
        "default_size": "1024x1792",
        "available_sizes": ["1024x1024", "1024x1792", "1792x1024"],
        "supports_negative_prompt": False,
        "supports_image_edit": True,
    },
    "imagen-4.0-apimart": {
        "name": "APIMart Imagen 4.0",
        "default_size": "1024x1792",
        "available_sizes": ["1024x1024", "1024x1792", "1792x1024"],
        "supports_negative_prompt": False,
        "supports_image_edit": False,
    },
    "flux-kontext-pro": {
        "name": "APIMart Flux Kontext Pro",
        "default_size": "1024x1792",
        "available_sizes": ["1024x1024", "1024x1792", "1792x1024"],
        "supports_negative_prompt": False,
        "supports_image_edit": True,
    },
    "gpt-4o-image": {
        "name": "APIMart GPT-4o Image",
        "default_size": "1024x1024",
        "available_sizes": ["1024x1024", "1024x1792", "1792x1024"],
        "supports_negative_prompt": False,
        "supports_image_edit": True,
    },
}


class ImageService:
    """Service layer around provider image generation."""

    def __init__(self, provider: BaseProvider):
        self.provider = provider

    async def generate_image(
        self,
        request: ImageRequest,
        user_id: Optional[int] = None,
        **kwargs,
    ) -> ImageResponse:
        """Generate images and normalize the provider response."""
        dyn_config = await get_dynamic_config(service_type="image")

        model = (
            request.model
            or dyn_config.default_model
            or ai_config.image.default_model
            or ai_config.openai.image_model
        )
        model_defaults = MODEL_DEFAULTS.get(model, {})

        size = request.size
        if not size and model_defaults.get("default_size"):
            size = model_defaults["default_size"]
        if not size:
            size = ai_config.image.default_size

        quality = request.quality or ai_config.image.default_quality

        merged_extra = dict(model_defaults.get("default_extra", {}))
        if request.extra_params:
            merged_extra.update(request.extra_params)

        logger.info(
            "Image generation request: user={}, model={}, size={}, has_negative_prompt={}, has_image={}, extra_keys={}",
            user_id,
            model,
            size,
            bool(request.negative_prompt),
            bool(request.image),
            sorted(merged_extra.keys()) if merged_extra else [],
        )

        provider_response = await self.provider.image_generate(
            prompt=request.prompt,
            model=model,
            size=size,
            quality=quality,
            n=request.n,
            negative_prompt=request.negative_prompt,
            image=request.image,
            extra_params=merged_extra or None,
            **kwargs,
        )

        images = [
            ImageData(
                url=item.url,
                b64_json=item.b64_json,
                revised_prompt=item.revised_prompt,
            )
            for item in (provider_response.images or [])
        ]

        if not images and (provider_response.url or provider_response.b64_json):
            images.append(
                ImageData(
                    url=provider_response.url,
                    b64_json=provider_response.b64_json,
                    revised_prompt=provider_response.revised_prompt,
                )
            )

        return ImageResponse(
            images=images,
            original_prompt=request.prompt,
            metadata=AIMetadata(
                model=provider_response.model or model,
                provider=self.provider.name,
                usage=None,
            ),
            seed=provider_response.seed,
            inference_time_ms=provider_response.inference_time_ms,
        )

    @staticmethod
    def get_available_models() -> ImageModelsResponse:
        """Return static model metadata for the frontend selector."""
        configured_models = ai_config.image.available_models or list(MODEL_DEFAULTS.keys())
        default_model = ai_config.image.default_model or ai_config.openai.image_model

        models = []
        for model_id in configured_models:
            defaults = MODEL_DEFAULTS.get(model_id, {})
            models.append(
                ImageModelInfo(
                    model_id=model_id,
                    name=defaults.get("name", model_id.split("/")[-1]),
                    default_size=defaults.get("default_size"),
                    available_sizes=defaults.get("available_sizes", []),
                    supports_negative_prompt=defaults.get(
                        "supports_negative_prompt", True
                    ),
                    supports_image_edit=defaults.get("supports_image_edit", False),
                    extra_info={
                        key: value
                        for key, value in defaults.items()
                        if key
                        not in {
                            "name",
                            "default_size",
                            "available_sizes",
                            "supports_negative_prompt",
                            "supports_image_edit",
                            "default_extra",
                        }
                    }
                    or None,
                )
            )

        return ImageModelsResponse(default_model=default_model, models=models)
