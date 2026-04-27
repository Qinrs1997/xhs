"""TOML → DB 配置同步服务

应用启动时，将 settings.toml 中的 AI 配置同步到数据库。
TOML 作为 source of truth，DB 记录如已存在则更新，不存在则创建。
"""

from app.core.logger import logger


class ConfigSyncService:
    """TOML → DB 配置同步服务"""

    async def sync_toml_to_db(self) -> dict:
        """
        将 settings.toml 的关键配置同步到数据库。

        同步策略：
        - LLM：同步 chat_model、available_models、base_url、timeout 等
        - Image：同步 default_model、available_models，base_url/api_key 复用 LLM
        - 同步后使 dynamic_config 缓存失效

        Returns:
            dict: 同步结果摘要 {"llm": "created/updated/skipped", "image": "...", "search": "..."}
        """
        from app.core.database import AsyncSessionLocal
        from app.ai.config import ai_config

        result = {"llm": "skipped", "image": "skipped", "search": "skipped"}

        try:
            async with AsyncSessionLocal() as session:
                # =========== LLM 同步 ===========
                llm_result = await self._sync_llm(session, ai_config)
                result["llm"] = llm_result

                # =========== Image 同步 ===========
                image_result = await self._sync_image(session, ai_config)
                result["image"] = image_result

                # =========== Search 同步 ===========
                search_result = await self._sync_search(session, ai_config)
                result["search"] = search_result

                await session.commit()

            # 使 dynamic_config 缓存失效
            from app.ai.services.dynamic_config import dynamic_config_service
            dynamic_config_service.invalidate()

            logger.info("TOML→DB 配置同步完成: LLM={}, Image={}, Search={}", result['llm'], result['image'], result['search'])

        except Exception as e:
            logger.error("TOML→DB 配置同步失败: {}", e)
            result["error"] = str(e)

        return result

    async def _sync_llm(self, session, ai_config) -> str:
        """同步 LLM 配置到 DB"""
        from app.models.ai import AIProvider
        from sqlalchemy import select

        # 查找 service_type="llm" + is_default=True 的记录
        stmt = select(AIProvider).where(
            AIProvider.service_type == "llm",
            AIProvider.is_default.is_(True),
            AIProvider.is_active.is_(True),
        )
        result = await session.execute(stmt)
        provider = result.scalar_one_or_none()

        openai_cfg = ai_config.openai
        available_models = openai_cfg.available_models or []

        if provider:
            # 已存在：更新关键字段
            provider.default_model = openai_cfg.chat_model
            provider.available_models = {"models": available_models}
            provider.base_url = openai_cfg.base_url
            provider.timeout = openai_cfg.timeout
            provider.max_retries = openai_cfg.max_retries
            provider.max_tokens = openai_cfg.default_max_tokens
            # api_key：如果 TOML/环境变量有值且与 DB 不同，则更新
            if openai_cfg.api_key and openai_cfg.api_key != provider.api_key:
                provider.api_key = openai_cfg.api_key
            session.add(provider)
            logger.info("LLM 配置已更新: model={}, models={}个", openai_cfg.chat_model, len(available_models))
            return "updated"
        else:
            # 不存在：创建新记录
            new_provider = AIProvider(
                name="硅基流动 (LLM)",
                provider_type="openai",
                service_type="llm",
                api_key=openai_cfg.api_key,
                base_url=openai_cfg.base_url,
                default_model=openai_cfg.chat_model,
                available_models={"models": available_models},
                timeout=openai_cfg.timeout,
                max_retries=openai_cfg.max_retries,
                max_tokens=openai_cfg.default_max_tokens,
                is_active=True,
                is_default=True,
                priority=100,
                description="TOML 自动同步创建的默认 LLM 服务商",
            )
            session.add(new_provider)
            logger.info("LLM 配置已创建: model={}, models={}个", openai_cfg.chat_model, len(available_models))
            return "created"

    async def _sync_image(self, session, ai_config) -> str:
        """同步 Image 配置到 DB"""
        from app.models.ai import AIProvider
        from sqlalchemy import select

        # 查找 service_type="image" + is_default=True 的记录
        stmt = select(AIProvider).where(
            AIProvider.service_type == "image",
            AIProvider.is_default.is_(True),
            AIProvider.is_active.is_(True),
        )
        result = await session.execute(stmt)
        provider = result.scalar_one_or_none()

        image_cfg = ai_config.image
        openai_cfg = ai_config.openai
        image_api_key = image_cfg.api_key or openai_cfg.api_key
        image_base_url = image_cfg.base_url or openai_cfg.base_url
        image_provider_name = (
            "APIMart (图片)"
            if "apimart" in (image_base_url or "").lower()
            else "硅基流动 (图片)"
        )
        available_models = image_cfg.available_models or []

        if provider:
            # 已存在：更新关键字段
            if provider.name in {"硅基流动 (图片)", "APIMart (图片)"}:
                provider.name = image_provider_name
            provider.default_model = image_cfg.default_model
            provider.available_models = {"models": available_models}
            provider.base_url = image_base_url
            if image_api_key and image_api_key != provider.api_key:
                provider.api_key = image_api_key
            # 将图片专属配置存入 extra_config
            provider.extra_config = {
                "default_size": image_cfg.default_size,
                "default_quality": image_cfg.default_quality,
            }
            session.add(provider)
            logger.info("Image 配置已更新: model={}, models={}个", image_cfg.default_model, len(available_models))
            return "updated"
        else:
            # 不存在：创建新记录
            new_provider = AIProvider(
                name=image_provider_name,
                provider_type="openai",
                service_type="image",
                api_key=image_api_key,
                base_url=image_base_url,
                default_model=image_cfg.default_model,
                available_models={"models": available_models},
                timeout=openai_cfg.timeout,
                max_retries=openai_cfg.max_retries,
                max_tokens=0,  # 图片不需要 max_tokens
                is_active=True,
                is_default=True,
                priority=100,
                description="TOML 自动同步创建的默认图片服务商",
                extra_config={
                    "default_size": image_cfg.default_size,
                    "default_quality": image_cfg.default_quality,
                },
            )
            session.add(new_provider)
            logger.info("Image 配置已创建: model={}, models={}个", image_cfg.default_model, len(available_models))
            return "created"

    async def _sync_search(self, session, ai_config) -> str:
        """同步 Search 配置到 DB"""
        from app.models.ai import AIProvider
        from sqlalchemy import select

        search_cfg = ai_config.search
        if not search_cfg.enabled:
            return "skipped (disabled)"

        # 查找 service_type="search" + is_default=True 的记录
        stmt = select(AIProvider).where(
            AIProvider.service_type == "search",
            AIProvider.is_default.is_(True),
            AIProvider.is_active.is_(True),
        )
        result = await session.execute(stmt)
        provider = result.scalar_one_or_none()

        openai_cfg = ai_config.openai
        search_api_key = search_cfg.api_key or openai_cfg.api_key

        # 构建 available_models 列表（实际是 provider 列表）
        available_providers = search_cfg.providers_fallback or [search_cfg.provider]

        if provider:
            # 已存在：更新关键字段
            provider.default_model = search_cfg.provider  # 默认搜索引擎名称
            provider.available_models = {"models": available_providers}
            provider.base_url = search_cfg.searxng_base_url or openai_cfg.base_url
            if search_api_key and search_api_key != provider.api_key:
                provider.api_key = search_api_key
            provider.extra_config = {
                "search_provider": search_cfg.provider,
                "max_results": search_cfg.max_results,
                "rate_limit_rpm": search_cfg.rate_limit_rpm,
                "providers_fallback": search_cfg.providers_fallback,
                "searxng_base_url": search_cfg.searxng_base_url,
            }
            session.add(provider)
            logger.info("Search 配置已更新: provider={}, fallback={}", search_cfg.provider, available_providers)
            return "updated"
        else:
            # 不存在：创建新记录
            new_provider = AIProvider(
                name="搜索服务 (DuckDuckGo)",
                provider_type="search",
                service_type="search",
                api_key=search_api_key,
                base_url=search_cfg.searxng_base_url or openai_cfg.base_url,
                default_model=search_cfg.provider,
                available_models={"models": available_providers},
                timeout=openai_cfg.timeout,
                max_retries=openai_cfg.max_retries,
                max_tokens=0,  # 搜索不需要 max_tokens
                is_active=True,
                is_default=True,
                priority=100,
                description="TOML 自动同步创建的默认搜索服务商",
                extra_config={
                    "search_provider": search_cfg.provider,
                    "max_results": search_cfg.max_results,
                    "rate_limit_rpm": search_cfg.rate_limit_rpm,
                    "providers_fallback": search_cfg.providers_fallback,
                    "searxng_base_url": search_cfg.searxng_base_url,
                },
            )
            session.add(new_provider)
            logger.info("Search 配置已创建: provider={}, fallback={}", search_cfg.provider, available_providers)
            return "created"


# 全局实例
config_sync_service = ConfigSyncService()
