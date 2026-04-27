"""Runtime AI provider configuration service.

The project can source provider settings from either:
1. the database (preferred, per ``service_type``), or
2. the static TOML/environment configuration as a fallback.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from app.core.logger import logger


@dataclass
class DynamicAIConfig:
    """Resolved runtime config for one AI service type."""

    provider_id: Optional[int] = None
    name: str = "default"
    provider_type: str = "openai"
    api_key: str = ""
    base_url: str = ""
    default_model: str = "gpt-3.5-turbo"
    available_models: list[str] = field(default_factory=list)
    timeout: int = 60
    max_retries: int = 3
    max_tokens: int = 4096
    loaded_at: datetime = field(default_factory=datetime.now)
    source: str = "toml"


class DynamicConfigService:
    """Singleton config loader with per-service-type caching."""

    _instance: Optional["DynamicConfigService"] = None
    _configs: Dict[str, DynamicAIConfig]
    _lock: asyncio.Lock

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._configs = {}
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    @property
    def config(self) -> DynamicAIConfig:
        """Synchronous convenience accessor for the default LLM config."""
        cached = self._configs.get("llm")
        if cached is None:
            cached = self._load_from_toml(service_type="llm")
            self._configs["llm"] = cached
        return cached

    async def get_config(self, service_type: str = "llm") -> DynamicAIConfig:
        """Load runtime config for ``service_type`` from DB, then TOML fallback."""
        async with self._lock:
            cached = self._configs.get(service_type)
            if cached is None:
                cached = await self._load_from_db(service_type=service_type)
                if cached is None:
                    cached = self._load_from_toml(service_type=service_type)
                self._configs[service_type] = cached
            return cached

    async def get_image_config(self) -> DynamicAIConfig:
        """Convenience wrapper for image provider config."""
        return await self.get_config(service_type="image")

    async def reload(self, service_type: str = "llm") -> DynamicAIConfig:
        """Force-refresh one service type."""
        async with self._lock:
            cached = await self._load_from_db(service_type=service_type)
            if cached is None:
                cached = self._load_from_toml(service_type=service_type)
                logger.info("AI config reloaded from TOML (type={})", service_type)
            else:
                logger.info(
                    "AI config reloaded from database: {} (type={})",
                    cached.name,
                    service_type,
                )
            self._configs[service_type] = cached
            return cached

    async def _load_from_db(
        self, service_type: str = "llm"
    ) -> Optional[DynamicAIConfig]:
        """Load the highest-priority active provider for one service type."""
        try:
            from sqlalchemy import select

            from app.core.database import AsyncSessionLocal
            from app.models.ai import AIProvider

            async with AsyncSessionLocal() as session:
                stmt = (
                    select(AIProvider)
                    .where(
                        AIProvider.is_active.is_(True),
                        AIProvider.service_type == service_type,
                    )
                    .order_by(AIProvider.is_default.desc(), AIProvider.priority.desc())
                    .limit(1)
                )

                result = await session.execute(stmt)
                provider = result.scalar_one_or_none()

                if provider is None:
                    return None

                models: list[str] = []
                if provider.available_models:
                    models = provider.available_models.get("models", [])

                return DynamicAIConfig(
                    provider_id=provider.id,
                    name=provider.name,
                    provider_type=provider.provider_type,
                    api_key=provider.api_key,
                    base_url=provider.base_url,
                    default_model=provider.default_model,
                    available_models=models,
                    timeout=provider.timeout,
                    max_retries=provider.max_retries,
                    max_tokens=provider.max_tokens,
                    source="database",
                )
        except Exception as exc:
            logger.warning(
                "Failed to load AI config from database (type={}): {}",
                service_type,
                exc,
            )
        return None

    def _load_from_toml(self, service_type: str = "llm") -> DynamicAIConfig:
        """Build a fallback config from static project settings."""
        try:
            from app.ai.config import ai_config

            if service_type == "image":
                return DynamicAIConfig(
                    name="toml_image",
                    provider_type="openai",
                    api_key=ai_config.image.api_key or ai_config.openai.api_key,
                    base_url=ai_config.image.base_url or ai_config.openai.base_url,
                    default_model=ai_config.image.default_model
                    or ai_config.openai.image_model,
                    available_models=ai_config.image.available_models or [],
                    timeout=ai_config.openai.timeout,
                    max_retries=ai_config.openai.max_retries,
                    max_tokens=0,
                    source="toml",
                )

            if service_type == "search":
                providers = ai_config.search.providers_fallback or [
                    ai_config.search.provider
                ]
                return DynamicAIConfig(
                    name="toml_search",
                    provider_type="search",
                    api_key=ai_config.search.api_key or ai_config.openai.api_key,
                    base_url=ai_config.search.searxng_base_url
                    or ai_config.openai.base_url,
                    default_model=ai_config.search.provider,
                    available_models=providers,
                    timeout=ai_config.openai.timeout,
                    max_retries=ai_config.openai.max_retries,
                    max_tokens=0,
                    source="toml",
                )

            return DynamicAIConfig(
                name="toml_llm",
                provider_type="openai",
                api_key=ai_config.openai.api_key,
                base_url=ai_config.openai.base_url,
                default_model=ai_config.openai.chat_model,
                available_models=ai_config.openai.available_models or [],
                timeout=ai_config.openai.timeout,
                max_retries=ai_config.openai.max_retries,
                max_tokens=ai_config.openai.default_max_tokens,
                source="toml",
            )
        except Exception as exc:
            logger.error("Failed to build TOML AI config (type={}): {}", service_type, exc)
            return DynamicAIConfig()

    def invalidate(self, service_type: Optional[str] = None) -> None:
        """Invalidate one cached config, or all configs when omitted."""
        if service_type:
            self._configs.pop(service_type, None)
            logger.info("AI config marked for refresh (type={})", service_type)
            return

        self._configs.clear()
        logger.info("AI config marked for refresh (all types)")


dynamic_config_service = DynamicConfigService()


async def get_dynamic_config(service_type: str = "llm") -> DynamicAIConfig:
    """Convenience wrapper used across providers/services."""
    return await dynamic_config_service.get_config(service_type=service_type)


async def reload_ai_config(service_type: str = "llm") -> DynamicAIConfig:
    """Force-refresh one cached runtime config."""
    return await dynamic_config_service.reload(service_type=service_type)
