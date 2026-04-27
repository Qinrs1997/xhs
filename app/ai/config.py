"""AI 模块配置

从项目配置系统读取 AI 相关配置，支持环境变量覆盖。

使用方式：
    from app.ai.config import ai_config

    if ai_config.enabled:
        print(f"使用模型: {ai_config.openai.default_model}")
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings


@dataclass
class OpenAIConfig:
    """OpenAI 配置"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    timeout: int = 60
    max_retries: int = 3

    # 模型配置
    chat_model: str = "gpt-4o-mini"
    summary_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    image_model: str = "dall-e-3"
    available_models: list[str] = field(default_factory=list)

    # 默认参数
    default_temperature: float = 0.7
    default_max_tokens: int = 4096


@dataclass
class ContextConfig:
    """上下文管理配置"""

    max_messages: int = 20  # 最大保留消息数
    max_tokens: int = 8000  # 最大上下文 token 数
    auto_summarize: bool = True  # 超限时自动总结压缩
    storage_type: str = "memory"  # memory | redis | database


@dataclass
class SearchConfig:
    """搜索服务配置"""

    enabled: bool = False
    provider: str = "duckduckgo"
    api_key: str = ""
    brave_api_key: str = ""
    max_results: int = 5
    rate_limit_rpm: int = 20
    providers_fallback: list[str] = field(default_factory=lambda: ["duckduckgo", "searxng"])
    searxng_base_url: str = "http://localhost:8080"


@dataclass
class ApimartConfig:
    """APIMart 异步出图轮询参数。

    部分图片模型（如 ``gpt-image-2``）在 APIMart 走异步任务：初始响应返回
    ``task_id``，需要再 ``GET /v1/tasks/{task_id}`` 轮询拿最终图 URL。
    以下参数控制等待节奏，全部在 ``settings.toml [ai.image.apimart]`` 配置，
    **禁止在代码里硬编码**。
    """

    initial_delay_seconds: int = 10
    poll_interval_seconds: int = 3
    task_timeout_seconds: int = 300


@dataclass
class BatchGridConfig:
    """网格合成生图模式的默认参数。

    模板可在 ``xhs_templates.image_grid_config`` JSON 中覆盖 rows/cols/cell_size
    等字段；未覆盖的字段退回这里的默认值。所有值来自
    ``settings.toml [ai.image.batch_grid]``，禁止硬编码。
    """

    enabled: bool = True
    default_rows: int = 2
    default_cols: int = 2
    default_cell_size: str = "512x896"
    split_upscale_enabled: bool = True
    split_target_cell_size: str = "1024x1792"
    max_pages_per_grid: int = 4
    grid_gap_px: int = 16
    supported_models: list[str] = field(
        default_factory=lambda: [
            "gpt-image-2",
            "flux-kontext-pro",
            "imagen-4.0-apimart",
            "gpt-4o-image",
        ]
    )
    blank_threshold: float = 0.6
    max_pixels: int = 4_194_304  # 2048 * 2048


@dataclass
class ImageConfig:
    """图像服务配置"""

    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    default_model: str = "black-forest-labs/FLUX.1-schnell"
    default_size: str = "1024x1792"
    default_quality: str = "standard"
    available_models: list[str] = field(default_factory=list)

    # 缩略图处理
    thumbnail_enabled: bool = True
    thumbnail_width: int = 720
    thumbnail_quality: int = 82
    thumbnail_format: str = "webp"
    persist_originals: bool = True
    download_timeout: int = 30

    # APIMart 异步轮询
    apimart: ApimartConfig = field(default_factory=ApimartConfig)

    # 网格合成生图（batch_grid 模式）
    batch_grid: BatchGridConfig = field(default_factory=BatchGridConfig)


@dataclass
class XHSConfig:
    """小红书图文生成配置"""

    max_concurrency: int = 5
    short_prompt_threshold: int = 1500


@dataclass
class PromptsConfig:
    """提示词管理配置"""

    enabled: bool = True
    templates_dir: str = "app/ai/prompts/templates"  # 内置模板目录
    custom_dir: str = "app/ai/prompts/custom"  # 自定义模板目录
    cache_enabled: bool = True  # 是否启用缓存
    default_language: str = "chinese"  # 默认语言模板


@dataclass
class AIConfig:
    """AI 模块主配置"""

    # 总开关
    enabled: bool = False
    default_provider: str = "openai"

    # 功能开关
    chat_enabled: bool = True
    summary_enabled: bool = True
    search_enabled: bool = False
    image_enabled: bool = False
    xhs_enabled: bool = False

    # 子配置
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    xhs: XHSConfig = field(default_factory=XHSConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)

    def __post_init__(self):
        """初始化后处理，支持环境变量覆盖 + 参数校验"""
        # OpenAI-compatible API key. Keep AI_* aliases in sync with settings.toml.
        env_api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if env_api_key:
            self.openai.api_key = env_api_key

        # OpenAI-compatible Base URL override.
        env_base_url = os.getenv("AI_BASE_URL") or os.getenv("OPENAI_BASE_URL", "")
        if env_base_url:
            self.openai.base_url = env_base_url

        image_api_key = os.getenv("IMAGE_API_KEY") or os.getenv("APIMART_API_KEY", "")
        if image_api_key:
            self.image.api_key = image_api_key

        image_base_url = os.getenv("IMAGE_BASE_URL") or os.getenv("APIMART_BASE_URL", "")
        if image_base_url:
            self.image.base_url = image_base_url

        # Tavily API Key 支持环境变量覆盖
        env_tavily_key = os.getenv("TAVILY_API_KEY", "")
        if env_tavily_key:
            self.search.api_key = env_tavily_key

        self._validate_concurrency()

    def _validate_concurrency(self):
        """校验并发配置合理性"""
        if self.xhs.max_concurrency < 1:
            self.xhs.max_concurrency = 1
        if self.xhs.max_concurrency > 20:
            import logging

            logging.getLogger(__name__).warning(
                "XHS max_concurrency=%d 较高，可能触发下游 API 限流",
                self.xhs.max_concurrency,
            )
        if self.search.rate_limit_rpm < self.xhs.max_concurrency:
            import logging

            logging.getLogger(__name__).warning(
                "搜索 rate_limit_rpm(%d) < XHS max_concurrency(%d)，批量搜索生成可能受限",
                self.search.rate_limit_rpm,
                self.xhs.max_concurrency,
            )


def _get_nested(config: dict, path: str, default=None):
    """从嵌套字典中按路径读取值"""
    keys = path.split(".")
    value = config
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


@lru_cache()
def get_ai_config() -> AIConfig:
    """
    获取 AI 配置实例（缓存）

    从项目 TOML 配置中读取 [ai] 部分
    """
    # 尝试从 settings 获取原始 TOML 配置
    try:
        from app.core.config import load_toml_config

        toml_config = load_toml_config(settings.APP_ENV)
        ai_section = toml_config.get("ai", {})
    except Exception:
        ai_section = {}

    # 构建配置
    config = AIConfig(
        enabled=ai_section.get("enabled", False),
        default_provider=ai_section.get("default_provider", "openai"),
        chat_enabled=ai_section.get("chat_enabled", True),
        summary_enabled=ai_section.get("summary_enabled", True),
        search_enabled=ai_section.get("search_enabled", False),
        image_enabled=ai_section.get("image_enabled", False),
        xhs_enabled=ai_section.get("xhs_enabled", False),
    )

    # OpenAI 配置
    openai_section = ai_section.get("openai", {})
    config.openai = OpenAIConfig(
        api_key=openai_section.get("api_key", ""),
        base_url=openai_section.get("base_url", "https://api.openai.com/v1"),
        timeout=openai_section.get("timeout", 60),
        max_retries=openai_section.get("max_retries", 3),
        chat_model=_get_nested(openai_section, "models.chat", "gpt-4o-mini"),
        summary_model=_get_nested(openai_section, "models.summary", "gpt-4o-mini"),
        embedding_model=_get_nested(openai_section, "models.embedding", "text-embedding-3-small"),
        image_model=_get_nested(openai_section, "models.image", "dall-e-3"),
        available_models=_get_nested(openai_section, "models.available", []),
        default_temperature=openai_section.get("default_temperature", 0.7),
        default_max_tokens=openai_section.get("default_max_tokens", 4096),
    )

    # 上下文配置
    context_section = ai_section.get("context", {})
    config.context = ContextConfig(
        max_messages=context_section.get("max_messages", 20),
        max_tokens=context_section.get("max_tokens", 8000),
        auto_summarize=context_section.get("auto_summarize", True),
        storage_type=context_section.get("storage_type", "memory"),
    )

    # 搜索配置
    search_section = ai_section.get("search", {})
    config.search = SearchConfig(
        enabled=search_section.get("enabled", False),
        provider=search_section.get("provider", "duckduckgo"),
        api_key=search_section.get("api_key", ""),
        brave_api_key=search_section.get("brave_api_key", ""),
        max_results=search_section.get("max_results", 5),
        rate_limit_rpm=search_section.get("rate_limit_rpm", 20),
        providers_fallback=search_section.get("providers_fallback", ["duckduckgo", "searxng"]),
        searxng_base_url=search_section.get("searxng_base_url", "http://localhost:8080"),
    )

    # 图像配置
    image_section = ai_section.get("image", {})
    apimart_section = image_section.get("apimart", {}) or {}
    batch_grid_section = image_section.get("batch_grid", {}) or {}
    config.image = ImageConfig(
        enabled=image_section.get("enabled", False),
        api_key=image_section.get("api_key", ""),
        base_url=image_section.get("base_url", ""),
        default_model=image_section.get("default_model", "black-forest-labs/FLUX.1-schnell"),
        default_size=image_section.get("default_size", "1024x1792"),
        default_quality=image_section.get("default_quality", "standard"),
        available_models=image_section.get("available_models", []),
        thumbnail_enabled=image_section.get("thumbnail_enabled", True),
        thumbnail_width=image_section.get("thumbnail_width", 720),
        thumbnail_quality=image_section.get("thumbnail_quality", 82),
        thumbnail_format=image_section.get("thumbnail_format", "webp"),
        persist_originals=image_section.get("persist_originals", True),
        download_timeout=image_section.get("download_timeout", 30),
        apimart=ApimartConfig(
            initial_delay_seconds=apimart_section.get("initial_delay_seconds", 10),
            poll_interval_seconds=apimart_section.get("poll_interval_seconds", 3),
            task_timeout_seconds=apimart_section.get("task_timeout_seconds", 180),
        ),
        batch_grid=BatchGridConfig(
            enabled=batch_grid_section.get("enabled", True),
            default_rows=batch_grid_section.get("default_rows", 2),
            default_cols=batch_grid_section.get("default_cols", 2),
            default_cell_size=batch_grid_section.get("default_cell_size", "512x896"),
            split_upscale_enabled=batch_grid_section.get("split_upscale_enabled", True),
            split_target_cell_size=batch_grid_section.get("split_target_cell_size", "1024x1792"),
            max_pages_per_grid=batch_grid_section.get("max_pages_per_grid", 4),
            grid_gap_px=batch_grid_section.get("grid_gap_px", 16),
            supported_models=batch_grid_section.get(
                "supported_models",
                [
                    "gpt-image-2",
                    "flux-kontext-pro",
                    "imagen-4.0-apimart",
                    "gpt-4o-image",
                ],
            ),
            blank_threshold=batch_grid_section.get("blank_threshold", 0.6),
            max_pixels=batch_grid_section.get("max_pixels", 4_194_304),
        ),
    )

    # XHS 配置
    xhs_section = ai_section.get("xhs", {})
    config.xhs = XHSConfig(
        max_concurrency=xhs_section.get("max_concurrency", 5),
        short_prompt_threshold=xhs_section.get("short_prompt_threshold", 1500),
    )

    # 环境变量覆盖
    config.__post_init__()

    return config


# 全局配置实例
ai_config = get_ai_config()
