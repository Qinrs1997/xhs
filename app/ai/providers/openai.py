"""Direct OpenAI-compatible provider implementation."""

from __future__ import annotations

import hashlib
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
    """Retry wrapper for transient OpenAI-compatible errors."""

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


class OpenAIProvider(BaseProvider):
    """Direct provider backed by the OpenAI Python SDK."""

    name = "openai"

    def __init__(self):
        self.config = ai_config.openai
        self._async_client = None
        self._current_config_hash: str | None = None

    def _get_config_hash(self, api_key: str, base_url: str, service_type: str) -> str:
        digest = hashlib.sha256(
            (api_key or "").encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:12]
        return f"{service_type}:{digest}:{base_url}"

    async def get_client(self, service_type: str = "llm"):
        """Return an SDK client configured for the requested service type."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("Please install openai>=1.0.0") from None

        dyn_config = await get_dynamic_config(service_type=service_type)
        new_hash = self._get_config_hash(
            dyn_config.api_key, dyn_config.base_url, service_type
        )

        if self._async_client is not None and self._current_config_hash == new_hash:
            return self._async_client

        await self._close_client()

        import httpx

        http_client = httpx.AsyncClient(trust_env=False)
        self._async_client = AsyncOpenAI(
            api_key=dyn_config.api_key,
            base_url=dyn_config.base_url,
            timeout=dyn_config.timeout,
            max_retries=dyn_config.max_retries,
            http_client=http_client,
        )
        self._current_config_hash = new_hash
        logger.info(
            "OpenAI-compatible client initialized from {} config, base_url={}",
            dyn_config.source,
            dyn_config.base_url,
        )
        return self._async_client

    async def _close_client(self) -> None:
        if self._async_client is not None:
            try:
                await self._async_client.close()
            except Exception as exc:
                logger.warning("Failed to close OpenAI client cleanly: {}", exc)
            self._async_client = None

    async def refresh_client(self) -> None:
        await self._close_client()
        self._current_config_hash = None
        logger.info("OpenAI client refreshed")

    def _handle_openai_error(self, error: Exception) -> None:
        error_message = str(error)

        try:
            from openai import (
                APIConnectionError,
                APITimeoutError,
                AuthenticationError,
                BadRequestError,
                RateLimitError,
            )

            if isinstance(error, RateLimitError):
                raise AIRateLimitError(
                    message="OpenAI-compatible API request rate limited",
                    retry_after=60,
                )
            if isinstance(error, AuthenticationError):
                raise AIProviderError(
                    message="OpenAI-compatible API authentication failed",
                    provider=self.name,
                    original_error=error_message,
                )
            if isinstance(error, BadRequestError):
                if "content_policy" in error_message.lower():
                    raise AIContentFilterError(message="Content was filtered")
                raise AIInvalidRequestError(
                    message=f"Invalid OpenAI-compatible request: {error_message}"
                )
            if isinstance(error, APITimeoutError):
                raise AITimeoutError(message="OpenAI-compatible API request timed out")
            if isinstance(error, APIConnectionError):
                raise AIProviderError(
                    message="Unable to connect to the OpenAI-compatible API",
                    provider=self.name,
                    original_error=error_message,
                )
        except ImportError:
            pass

        lower = error_message.lower()
        if "rate_limit" in lower:
            raise AIRateLimitError()
        if "quota" in lower or "insufficient" in lower:
            raise AIQuotaExceededError()
        if "timeout" in lower:
            raise AITimeoutError()

        raise AIProviderError(
            message=f"OpenAI-compatible API call failed: {error_message}",
            provider=self.name,
            original_error=error_message,
        )

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

        dyn_config = await get_dynamic_config(service_type="llm")
        model = model or dyn_config.default_model
        max_tokens = max_tokens or dyn_config.max_tokens
        start_time = time.time()

        try:
            client = await self.get_client(service_type="llm")
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            logger.debug(
                "OpenAI-compatible chat completed: model={}, tokens={}, time={}ms",
                model,
                response.usage.total_tokens if response.usage else 0,
                elapsed_ms,
            )

            return ChatResponse(
                content=response.choices[0].message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                finish_reason=response.choices[0].finish_reason or "stop",
                raw_response=response,
            )
        except Exception as exc:
            logger.error("OpenAI-compatible chat failed: {}", exc)
            self._handle_openai_error(exc)

    async def chat_completion_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[ChatChunk]:
        dyn_config = await get_dynamic_config(service_type="llm")
        model = model or dyn_config.default_model
        max_tokens = max_tokens or dyn_config.max_tokens
        start_time = time.time()

        try:
            client = await self.get_client(service_type="llm")
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield ChatChunk(
                        content=chunk.choices[0].delta.content,
                        is_final=chunk.choices[0].finish_reason is not None,
                        finish_reason=chunk.choices[0].finish_reason,
                    )

            yield ChatChunk(content="", is_final=True, finish_reason="stop")

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.debug(
                "OpenAI-compatible streaming chat completed: model={}, time={}ms",
                model,
                elapsed_ms,
            )
        except Exception as exc:
            logger.error("OpenAI-compatible streaming chat failed: {}", exc)
            self._handle_openai_error(exc)

    @with_retry(max_attempts=3, min_wait=1, max_wait=10)
    async def embedding(
        self,
        text: str | list[str],
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        dyn_config = await get_dynamic_config(service_type="llm")
        model = model or self.config.embedding_model or dyn_config.default_model
        inputs = [text] if isinstance(text, str) else text

        try:
            client = await self.get_client(service_type="llm")
            response = await client.embeddings.create(model=model, input=inputs)
            return EmbeddingResponse(
                embeddings=[item.embedding for item in response.data],
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            )
        except Exception as exc:
            logger.error("OpenAI-compatible embedding failed: {}", exc)
            self._handle_openai_error(exc)

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
        dyn_config = await get_dynamic_config(service_type="image")
        model = model or dyn_config.default_model or self.config.image_model
        normalized_size = (
            normalize_apimart_size(size)
            if is_apimart_base_url(dyn_config.base_url)
            else size
        ) or "1024x1024"
        quality = quality or "standard"

        gen_kwargs = {}
        if extra_params:
            gen_kwargs.update(extra_params)
        if negative_prompt:
            gen_kwargs["negative_prompt"] = negative_prompt
        if image:
            if is_apimart_base_url(dyn_config.base_url):
                gen_kwargs["image_urls"] = [image]
            else:
                gen_kwargs["image"] = image
        gen_kwargs.update(kwargs)

        try:
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
                    model=model,
                    prompt=prompt,
                    size=normalized_size,
                    quality=quality,
                    n=n,
                    extra_params=apimart_extra_params or None,
                )
                images = [
                    ImageResponseItem(url=url)
                    for url in extract_inline_image_urls(raw)
                ]
                if not images:
                    apimart_cfg = ai_config.image.apimart
                    for task_id in extract_task_ids(raw):
                        urls = await wait_for_task_images(
                            base_url=dyn_config.base_url,
                            api_key=dyn_config.api_key,
                            task_id=task_id,
                            initial_delay_seconds=apimart_cfg.initial_delay_seconds,
                            poll_interval_seconds=apimart_cfg.poll_interval_seconds,
                            timeout_seconds=apimart_cfg.task_timeout_seconds,
                        )
                        images.extend(ImageResponseItem(url=url) for url in urls)

                first = images[0] if images else ImageResponseItem()
                return ImageResponse(
                    url=first.url,
                    b64_json=first.b64_json,
                    revised_prompt=first.revised_prompt,
                    model=model,
                    images=images,
                )

            client = await self.get_client(service_type="image")
            response = await client.images.generate(
                model=model,
                prompt=prompt,
                size=normalized_size,
                quality=quality,
                n=n,
                response_format=response_format,
                **gen_kwargs,
            )

            images = [
                ImageResponseItem(url=url)
                for url in extract_inline_image_urls(response)
            ]

            if not images and is_apimart_base_url(dyn_config.base_url):
                task_ids = extract_task_ids(response)
                for task_id in task_ids:
                    urls = await wait_for_task_images(
                        base_url=dyn_config.base_url,
                        api_key=dyn_config.api_key,
                        task_id=task_id,
                    )
                    images.extend(ImageResponseItem(url=url) for url in urls)

            first = images[0] if images else ImageResponseItem()
            return ImageResponse(
                url=first.url,
                b64_json=first.b64_json,
                revised_prompt=first.revised_prompt,
                model=model,
                images=images,
            )
        except Exception as exc:
            logger.error("OpenAI-compatible image generation failed: {}", exc)
            self._handle_openai_error(exc)
