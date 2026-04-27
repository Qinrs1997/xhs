"""LiteLLM provider implementation."""

from __future__ import annotations

import time
from functools import wraps
from typing import AsyncIterator, Optional

from app.ai.config import ai_config
from app.ai.exceptions import (
    AIContentFilterError,
    AIInvalidRequestError,
    AIProviderError,
    AIQuotaExceededError,
    AIRateLimitError,
    AITimeoutError,
)
from app.ai.providers.apimart import (
    call_apimart_image_generation_raw,
    extract_inline_image_urls,
    extract_task_ids,
    is_apimart_base_url,
    normalize_apimart_size,
    wait_for_task_images,
)
from app.ai.providers.base import (
    BaseProvider,
    ChatChunk,
    ChatResponse,
    EmbeddingResponse,
    ImageResponse,
    ImageResponseItem,
)
from app.ai.services.dynamic_config import get_dynamic_config
from app.core.logger import logger

RETRYABLE_EXCEPTIONS = (
    AITimeoutError,
    AIRateLimitError,
    ConnectionError,
    TimeoutError,
)


def with_retry(max_attempts: int = 3, min_wait: float = 1, max_wait: float = 10):
    """Retry wrapper for transient provider errors."""

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(self, *args, **kwargs)
                except RETRYABLE_EXCEPTIONS as exc:
                    last_exception = exc
                    wait_time = min(min_wait * (2**attempt), max_wait)
                    logger.warning(
                        "AI request failed (attempt {}/{}), retrying in {:.1f}s: {}",
                        attempt + 1,
                        max_attempts,
                        wait_time,
                        exc,
                    )
                    if attempt < max_attempts - 1:
                        import asyncio

                        await asyncio.sleep(wait_time)
                except Exception:
                    raise

            logger.error("AI request failed after {} attempts", max_attempts)
            raise last_exception

        return wrapper

    return decorator


def _handle_litellm_error(error: Exception, provider_name: str = "litellm") -> None:
    """Convert LiteLLM exceptions into project-level AI errors."""
    error_message = str(error)

    try:
        import litellm

        if isinstance(error, litellm.RateLimitError):
            raise AIRateLimitError(message="API request rate limited", retry_after=60)
        if isinstance(error, litellm.AuthenticationError):
            raise AIProviderError(
                message="API authentication failed, please check the API key",
                provider=provider_name,
                original_error=error_message,
            )
        if isinstance(error, litellm.BadRequestError):
            if "content_policy" in error_message.lower() or "content_filter" in error_message.lower():
                raise AIContentFilterError(message="Content was filtered by the upstream provider")
            raise AIInvalidRequestError(message=f"Invalid API request: {error_message}")
        if isinstance(error, litellm.Timeout):
            raise AITimeoutError(message="API request timed out")
        if isinstance(error, litellm.APIConnectionError):
            raise AIProviderError(
                message="Unable to connect to the AI API",
                provider=provider_name,
                original_error=error_message,
            )
        if isinstance(error, litellm.BudgetExceededError):
            raise AIQuotaExceededError(message="API quota exceeded")
    except ImportError:
        pass

    lower_msg = error_message.lower()
    if "rate_limit" in lower_msg or "rate limit" in lower_msg:
        raise AIRateLimitError()
    if "quota" in lower_msg or "insufficient" in lower_msg:
        raise AIQuotaExceededError()
    if "timeout" in lower_msg:
        raise AITimeoutError()

    raise AIProviderError(
        message=f"AI API call failed: {error_message}",
        provider=provider_name,
        original_error=error_message,
    )


class LiteLLMProvider(BaseProvider):
    """Unified LiteLLM-based provider."""

    name = "litellm"

    def __init__(self):
        self.config = ai_config.openai
        self._initialized = False
        self._setup_litellm()

    def _setup_litellm(self) -> None:
        try:
            import litellm

            litellm.suppress_debug_info = True
            litellm.set_verbose = False
            litellm.request_timeout = self.config.timeout
            litellm.drop_params = True

            self._initialized = True
            logger.info("LiteLLM provider initialized")
        except ImportError as exc:
            raise ImportError("Please install litellm: pip install litellm") from exc

    def _build_api_params(self, dyn_config) -> dict:
        params = {
            "api_key": dyn_config.api_key,
            "timeout": dyn_config.timeout,
        }
        if dyn_config.base_url and "openai.com" not in dyn_config.base_url:
            params["api_base"] = dyn_config.base_url
        return params

    def _resolve_model(self, model: Optional[str], dyn_config) -> str:
        if not model:
            model = dyn_config.default_model

        if "/" in model and model.split("/")[0] in (
            "openai",
            "anthropic",
            "gemini",
            "dashscope",
            "azure",
            "bedrock",
            "vertex_ai",
            "cohere",
            "deepseek",
            "groq",
            "mistral",
            "ollama",
        ):
            return model

        if dyn_config.base_url and "openai.com" not in dyn_config.base_url:
            return f"openai/{model}"

        return model

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def chat_completion(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs,
    ) -> ChatResponse | AsyncIterator[ChatChunk]:
        if stream:
            return self.chat_completion_stream(
                messages, model, temperature, max_tokens, **kwargs
            )

        import litellm

        dyn_config = await get_dynamic_config(service_type="llm")
        resolved_model = self._resolve_model(model, dyn_config)
        max_tokens = max_tokens or dyn_config.max_tokens
        api_params = self._build_api_params(dyn_config)
        start_time = time.time()

        try:
            response = await litellm.acompletion(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **api_params,
                **kwargs,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = response.usage

            logger.debug(
                "LiteLLM chat completed: model={}, tokens={}, time={}ms",
                resolved_model,
                usage.total_tokens if usage else "N/A",
                elapsed_ms,
            )

            return ChatResponse(
                content=response.choices[0].message.content or "",
                model=response.model or resolved_model,
                usage={
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
                finish_reason=response.choices[0].finish_reason or "stop",
                raw_response=response,
            )
        except Exception as exc:
            logger.error("LiteLLM chat failed: {}", exc)
            _handle_litellm_error(exc, self.name)

    async def chat_completion_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[ChatChunk]:
        import litellm

        dyn_config = await get_dynamic_config(service_type="llm")
        resolved_model = self._resolve_model(model, dyn_config)
        max_tokens = max_tokens or dyn_config.max_tokens
        api_params = self._build_api_params(dyn_config)
        start_time = time.time()

        try:
            response = await litellm.acompletion(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **api_params,
                **kwargs,
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield ChatChunk(
                        content=chunk.choices[0].delta.content,
                        is_final=chunk.choices[0].finish_reason is not None,
                        finish_reason=chunk.choices[0].finish_reason,
                    )

            yield ChatChunk(content="", is_final=True, finish_reason="stop")

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug(
                "LiteLLM streaming chat completed: model={}, time={}ms",
                resolved_model,
                elapsed_ms,
            )
        except Exception as exc:
            logger.error("LiteLLM streaming chat failed: {}", exc)
            _handle_litellm_error(exc, self.name)

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def embedding(
        self,
        text: str | list[str],
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        import litellm

        dyn_config = await get_dynamic_config(service_type="llm")
        resolved_model = self._resolve_model(model or self.config.embedding_model, dyn_config)
        api_params = self._build_api_params(dyn_config)

        inputs = [text] if isinstance(text, str) else text

        try:
            response = await litellm.aembedding(
                model=resolved_model,
                input=inputs,
                **api_params,
            )
            return EmbeddingResponse(
                embeddings=[item["embedding"] for item in response.data],
                model=response.model or resolved_model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            )
        except Exception as exc:
            logger.error("LiteLLM embedding failed: {}", exc)
            _handle_litellm_error(exc, self.name)

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def image_generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        n: int = 1,
        negative_prompt: Optional[str] = None,
        image: Optional[str] = None,
        extra_params: Optional[dict] = None,
        response_format: str = "url",
        **kwargs,
    ) -> ImageResponse:
        import litellm

        dyn_config = await get_dynamic_config(service_type="image")
        model = model or dyn_config.default_model or self.config.image_model
        resolved_model = self._resolve_model(model, dyn_config)
        api_params = self._build_api_params(dyn_config)
        normalized_size = (
            normalize_apimart_size(size)
            if is_apimart_base_url(dyn_config.base_url)
            else size
        )

        gen_params = {
            "model": resolved_model,
            "prompt": prompt,
            "n": n,
            "response_format": response_format,
            **api_params,
        }

        model_lower = model.lower()
        is_qwen_edit = "qwen" in model_lower and "edit" in model_lower
        if normalized_size and not is_qwen_edit:
            gen_params["size"] = normalized_size
        if quality:
            gen_params["quality"] = quality
        if negative_prompt:
            gen_params["negative_prompt"] = negative_prompt
        if image:
            if is_apimart_base_url(dyn_config.base_url):
                gen_params["image_urls"] = [image]
            else:
                gen_params["image"] = image
        if extra_params:
            gen_params.update(extra_params)
        gen_params.update(kwargs)

        logger.debug(
            "LiteLLM image request: model={}, size={}, has_negative_prompt={}, has_image={}, extra_keys={}",
            resolved_model,
            normalized_size,
            bool(negative_prompt),
            bool(image),
            sorted(extra_params.keys()) if extra_params else [],
        )

        try:
            # ---- APIMart 走直连(P2-A7i) --------------------------------
            # LiteLLM 的 ImageResponse pydantic 模型只声明 OpenAI 规范字段,
            # 会把 APIMart 的顶层 `id="task_01..."` 静默丢掉,导致异步任务
            # 无法轮询。改走直连 httpx 拿原始 JSON,确保 id 字段能被抽到。
            if is_apimart_base_url(dyn_config.base_url):
                apimart_extra_params: dict = {}
                if extra_params:
                    apimart_extra_params.update(extra_params)
                if kwargs:
                    apimart_extra_params.update(kwargs)
                if image:
                    existing_image_urls = apimart_extra_params.get("image_urls")
                    image_urls: list[str] = []
                    if isinstance(existing_image_urls, list):
                        image_urls.extend(str(url) for url in existing_image_urls if url)
                    elif existing_image_urls:
                        image_urls.append(str(existing_image_urls))
                    image_urls.append(image)
                    apimart_extra_params["image_urls"] = image_urls

                raw = await call_apimart_image_generation_raw(
                    base_url=dyn_config.base_url,
                    api_key=dyn_config.api_key,
                    model=model,  # 不带 "openai/" 前缀
                    prompt=prompt,
                    size=normalized_size if not is_qwen_edit else None,
                    quality=quality,
                    n=n,
                    extra_params=apimart_extra_params or None,
                )
                images: list[ImageResponseItem] = [
                    ImageResponseItem(url=url)
                    for url in extract_inline_image_urls(raw)
                ]
                if not images:
                    task_ids = extract_task_ids(raw)
                    if task_ids:
                        apimart_cfg = ai_config.image.apimart
                        for task_id in task_ids:
                            urls = await wait_for_task_images(
                                base_url=dyn_config.base_url,
                                api_key=dyn_config.api_key,
                                task_id=task_id,
                                initial_delay_seconds=apimart_cfg.initial_delay_seconds,
                                poll_interval_seconds=apimart_cfg.poll_interval_seconds,
                                timeout_seconds=apimart_cfg.task_timeout_seconds,
                            )
                            images.extend(ImageResponseItem(url=url) for url in urls)
                    else:
                        logger.warning(
                            "APIMart direct image gen: raw body has neither URL "
                            "nor task_id. model={}, top_keys={}, body_preview={!r:.500}",
                            model,
                            sorted(raw.keys()) if isinstance(raw, dict) else None,
                            raw,
                        )

                logger.info(
                    "APIMart direct image generation completed: model={}, "
                    "images={}",
                    model,
                    len(images),
                )
                first = images[0] if images else ImageResponseItem()
                return ImageResponse(
                    url=first.url,
                    b64_json=first.b64_json,
                    revised_prompt=first.revised_prompt,
                    model=model,
                    images=images,
                    seed=None,
                    inference_time_ms=None,
                )

            # ---- 非 APIMart 走原 LiteLLM 路径 -------------------------
            response = await litellm.aimage_generation(**gen_params)

            images = [
                ImageResponseItem(url=url)
                for url in extract_inline_image_urls(response)
            ]

            if not images and is_apimart_base_url(dyn_config.base_url):
                task_ids = extract_task_ids(response)
                if task_ids:
                    # Async image task → poll APIMart /tasks/{id} until done.
                    # Poll timings come from ai_config.image.apimart
                    # (settings.toml [ai.image.apimart]); do NOT hardcode.
                    apimart_cfg = ai_config.image.apimart
                    for task_id in task_ids:
                        urls = await wait_for_task_images(
                            base_url=dyn_config.base_url,
                            api_key=dyn_config.api_key,
                            task_id=task_id,
                            initial_delay_seconds=apimart_cfg.initial_delay_seconds,
                            poll_interval_seconds=apimart_cfg.poll_interval_seconds,
                            timeout_seconds=apimart_cfg.task_timeout_seconds,
                        )
                        images.extend(ImageResponseItem(url=url) for url in urls)
                else:
                    # Neither inline URLs nor task_ids. Dump the full shape
                    # for debug so we can quickly spot schema drift or
                    # prompt-induced empty responses in the future. We print
                    # both keys AND scalar values at the top level (not the
                    # whole `data` tree which could be huge) so new response
                    # variants with renamed id fields are immediately visible.
                    raw = (
                        response.model_dump()
                        if hasattr(response, "model_dump")
                        else (response if isinstance(response, dict) else {})
                    )
                    top_level_scalars: dict[str, object] = {}
                    if isinstance(raw, dict):
                        for key, val in raw.items():
                            if key == "data":
                                continue
                            if isinstance(val, (str, int, float, bool)) or val is None:
                                top_level_scalars[key] = val
                    data_preview = raw.get("data") if isinstance(raw, dict) else None
                    # 额外 dump LiteLLM 的私有字段,有些 SDK 版本把原始 API
                    # 响应放在 _hidden_params / _response_headers 里,用于
                    # 诊断 "LiteLLM pydantic 过滤掉了 apimart 的 id 字段"
                    # 这类场景 (P2-A7f)。
                    hidden_params = getattr(response, "_hidden_params", None)
                    response_headers = getattr(response, "_response_headers", None)
                    logger.warning(
                        "APIMart image response has neither URLs nor task_ids; "
                        "likely prompt rejected, response schema changed, or "
                        "LiteLLM dropped non-OpenAI fields. "
                        "model={}, top_keys={}, top_scalars={}, "
                        "data_type={}, data_preview={!r:.300}, "
                        "hidden_params_preview={!r:.400}, "
                        "response_headers_preview={!r:.200}",
                        model,
                        sorted(raw.keys()) if isinstance(raw, dict) else None,
                        top_level_scalars,
                        type(data_preview).__name__,
                        data_preview,
                        hidden_params,
                        response_headers,
                    )

            raw = response.model_extra if hasattr(response, "model_extra") else {}
            seed = raw.get("seed") if isinstance(raw, dict) else None
            timings = raw.get("timings", {}) if isinstance(raw, dict) else {}
            inference_time_ms = int(timings.get("inference", 0)) if timings else None
            first = images[0] if images else ImageResponseItem()

            logger.info(
                "LiteLLM image generation completed: model={}, images={}, seed={}, inference_time={}ms",
                model,
                len(images),
                seed,
                inference_time_ms,
            )

            return ImageResponse(
                url=first.url,
                b64_json=first.b64_json,
                revised_prompt=first.revised_prompt,
                model=model,
                images=images,
                seed=seed,
                inference_time_ms=inference_time_ms,
            )
        except Exception as exc:
            logger.error("LiteLLM image generation failed: {}", exc)
            _handle_litellm_error(exc, self.name)

    async def health_check(self) -> bool:
        try:
            await self.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
