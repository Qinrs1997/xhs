"""图像 Schema

定义图像生成相关的请求和响应模型。
支持硅基流动多模型（FLUX、Qwen-Image、Kolors 等）。
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.common import AIMetadata


class ImageRequest(BaseModel):
    """图像生成请求

    支持多种图片模型，参数灵活可选：
    - FLUX: 标准文生图，支持多种尺寸
    - Qwen-Image-Edit: 图生图/编辑，需传 image，不支持 size
    - Kolors: 文生图，支持 batch_size、guidance_scale
    """
    prompt: str = Field(
        description="图像描述",
        min_length=1,
        max_length=4000,
    )
    model: Optional[str] = Field(
        default=None,
        description="图片模型名称（如 black-forest-labs/FLUX.1-schnell、Qwen/Qwen-Image-Edit-2509）",
    )
    size: Optional[str] = Field(
        default=None,
        pattern=r"^\d+x\d+$",
        description="图像尺寸（WxH 格式，如 1024x1024）。未指定时由模型默认值决定",
    )
    quality: Optional[str] = Field(
        default=None,
        description="图像质量（如 standard、hd）",
    )
    style: Optional[str] = Field(
        default=None,
        description="风格（不同模型支持不同风格）",
    )
    n: int = Field(
        default=1,
        ge=1,
        le=4,
        description="生成数量（部分模型支持 batch_size）",
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        max_length=4000,
        description="反向提示词（描述不想出现的内容，硅基流动支持）",
    )
    image: Optional[str] = Field(
        default=None,
        description="参考图（base64 或 URL，用于图生图/编辑场景）",
    )
    extra_params: Optional[dict] = Field(
        default=None,
        description="透传给模型的额外参数（如 cfg、num_inference_steps、guidance_scale 等）",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "summary": "文生图(FLUX)",
                    "value": {
                        "prompt": "一只可爱的橘猫在阳光下打盹,水彩画风格",
                        "size": "1024x1024",
                    },
                },
                {
                    "summary": "图生图编辑(Qwen-Image-Edit)",
                    "value": {
                        "prompt": "把背景换成星空",
                        "model": "Qwen/Qwen-Image-Edit-2509",
                        "image": "https://example.com/cat.jpg",
                    },
                },
                {
                    "summary": "指定模型和负面提示词",
                    "value": {
                        "prompt": "未来城市的天际线,赛博朋克风格",
                        "model": "Kwai-Kolors/Kolors",
                        "size": "1024x1024",
                        "negative_prompt": "模糊/低质量/变形",
                        "extra_params": {
                            "guidance_scale": 7.5,
                            "num_inference_steps": 25,
                        },
                    },
                },
            ]
        }
    )


class ImageData(BaseModel):
    """单张图像数据"""
    url: Optional[str] = Field(
        default=None,
        description="图像 URL"
    )
    b64_json: Optional[str] = Field(
        default=None,
        description="Base64 编码的图像数据"
    )
    revised_prompt: Optional[str] = Field(
        default=None,
        description="优化后的提示词"
    )


class ImageResponse(BaseModel):
    """图像生成响应"""
    images: list[ImageData] = Field(
        description="生成的图像列表"
    )
    original_prompt: str = Field(
        description="原始提示词"
    )
    metadata: AIMetadata = Field(
        description="响应元数据"
    )
    seed: Optional[int] = Field(
        default=None,
        description="生成种子（可用于复现结果）"
    )
    inference_time_ms: Optional[int] = Field(
        default=None,
        description="推理耗时（毫秒）"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "images": [
                    {
                        "url": "https://example.com/generated-image.png",
                        "revised_prompt": None,
                    }
                ],
                "original_prompt": "一只可爱的橘猫在阳光下打盹",
                "metadata": {
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "provider": "litellm",
                },
                "seed": 12345,
                "inference_time_ms": 2300,
            }
        }
    )


class ImageModelInfo(BaseModel):
    """图片模型信息（用于前端展示模型选择器）"""
    model_id: str = Field(description="模型 ID")
    name: str = Field(description="显示名称")
    default_size: Optional[str] = Field(default=None, description="默认尺寸")
    available_sizes: list[str] = Field(default_factory=list, description="可用尺寸列表")
    supports_negative_prompt: bool = Field(default=True, description="是否支持反向提示词")
    supports_image_edit: bool = Field(default=False, description="是否支持图生图/编辑")
    extra_info: Optional[dict] = Field(default=None, description="额外信息")


class ImageModelsResponse(BaseModel):
    """可用图片模型列表响应"""
    default_model: str = Field(description="默认模型 ID")
    models: list[ImageModelInfo] = Field(description="可用模型列表")
