"""Helpers for APIMart OpenAI-compatible integrations.

APIMart exposes OpenAI-compatible request formats, but many image models are
asynchronous: the initial response returns a ``task_id`` and the final image
URL must be fetched from ``GET /v1/tasks/{task_id}``.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from app.core.logger import logger

# APIMart task IDs always start with ``task_`` followed by alphanum/underscore.
# The regex is deliberately strict (at least 10 chars after the prefix) so we
# don't accidentally match conversational "task_id" words in error messages.
_APIMART_TASK_ID_RE = re.compile(r"task_[A-Za-z0-9]{10,}")


APIMART_HOST = "api.apimart.ai"
APIMART_SUPPORTED_IMAGE_RATIOS = {
    "1:1": 1.0,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "5:4": 5 / 4,
    "4:5": 4 / 5,
    "2:1": 2.0,
    "1:2": 1 / 2,
    "21:9": 21 / 9,
    "9:21": 9 / 21,
}
_GPT_IMAGE_2_EXTRA_KEYS = {"image_urls", "official_fallback"}


def _apimart_defaults() -> tuple[int, int, int]:
    """Read (initial_delay, poll_interval, task_timeout) from ai_config.

    Lazy-imported so this module stays importable even when the AI layer is
    not fully initialized yet (e.g. during tests with `APP_ENV=test`).
    Falls back to the historical defaults (10s / 3s / 180s) if config can't
    be loaded.
    """
    try:
        from app.ai.config import ai_config

        cfg = ai_config.image.apimart
        return (
            cfg.initial_delay_seconds,
            cfg.poll_interval_seconds,
            cfg.task_timeout_seconds,
        )
    except Exception:  # pragma: no cover - defensive fallback
        return (10, 3, 180)


def is_apimart_base_url(base_url: str | None) -> bool:
    """Return ``True`` when the configured base URL points to APIMart."""
    if not base_url:
        return False
    return APIMART_HOST in base_url.lower()


def normalize_apimart_size(size: str | None) -> str | None:
    """Map pixel sizes used by the XHS UI to APIMart ratio-based sizes."""
    if not size:
        return size
    size = size.strip()
    if size in APIMART_SUPPORTED_IMAGE_RATIOS:
        return size

    size_map = {
        "1024x1024": "1:1",
        "1024x1792": "9:16",
        "1792x1024": "16:9",
        "768x1024": "3:4",
        "1024x768": "4:3",
        "960x1280": "3:4",
        "1280x960": "4:3",
        "720x1280": "9:16",
        "1280x720": "16:9",
        "720x1440": "1:2",
        "1440x720": "2:1",
        "1024x1536": "2:3",
        "1536x1024": "3:2",
        "1024x1280": "4:5",
        "1280x1024": "5:4",
        # Batch-grid composites include separator gaps, so their pixel size is
        # slightly off the clean APIMart ratio. Keep the provider request on a
        # supported ratio instead of sending arbitrary WxH values such as
        # 1024x2064, which APIMart rejects before returning an async task id.
        "1024x2048": "1:2",
        "1024x2064": "1:2",
        "2048x1024": "2:1",
        "2064x1024": "2:1",
        "1024x3072": "9:21",
        "1024x3104": "9:21",
        "3072x1024": "21:9",
        "3104x1024": "21:9",
        "2048x2048": "1:1",
        "2064x2064": "1:1",
        "1040x1808": "9:16",
    }
    if size in size_map:
        return size_map[size]

    match = re.fullmatch(r"(\d+)x(\d+)", size.strip().lower())
    if not match:
        return size

    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return size

    aspect = width / height
    best_ratio, best_aspect = min(
        APIMART_SUPPORTED_IMAGE_RATIOS.items(),
        key=lambda item: abs(aspect - item[1]) / item[1],
    )
    # 4% tolerance covers grid separator gaps without forcing unsupported
    # extreme canvases (for example 1:3) into the wrong APIMart size.
    if abs(aspect - best_aspect) / best_aspect <= 0.04:
        return best_ratio

    return size


def _is_supported_apimart_ratio(size: str | None) -> bool:
    return bool(size and size in APIMART_SUPPORTED_IMAGE_RATIOS)


def _is_gpt_image_2(model: str | None) -> bool:
    return (model or "").strip().lower() == "gpt-image-2"


def _to_plain_dict(value: Any) -> dict[str, Any]:
    """Best-effort conversion of SDK objects to a plain dictionary."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            dumped = value.dict()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        raw = {key: val for key, val in vars(value).items() if not key.startswith("_")}
        if raw:
            return raw
    return {}


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _normalize_image_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for item in _to_list(value):
        if item is None:
            continue
        text = str(item).strip()
        if text:
            urls.append(text)
    return urls


def _extract_urls(value: Any) -> list[str]:
    """Extract URL strings from a variety of APIMart/OpenAI response shapes."""
    urls: list[str] = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            urls.extend(_extract_urls(item))
        return urls
    if isinstance(value, dict):
        for key in ("url", "urls", "image_url", "image_urls"):
            if key in value:
                urls.extend(_extract_urls(value.get(key)))
    return [url for url in urls if isinstance(url, str) and url]


def extract_inline_image_urls(response: Any) -> list[str]:
    """Extract image URLs already present in an image generation response."""
    response_dict = _to_plain_dict(response)
    data = response_dict.get("data", getattr(response, "data", None))
    urls: list[str] = []

    for item in _to_list(data):
        urls.extend(_extract_urls(_to_plain_dict(item)))

    return urls


_TASK_ID_CANDIDATE_KEYS = (
    "task_id",
    "id",
    "job_id",
    "request_id",
)


def _looks_like_apimart_task_id(value: Any) -> bool:
    """Heuristic: APIMart task IDs typically start with ``task_`` / ``job_``.

    Plain ``chatcmpl-xxx`` or UUIDs from other providers are ignored to avoid
    false positives triggering useless polls.
    """
    if not isinstance(value, str) or not value:
        return False
    lowered = value.lower()
    return lowered.startswith(("task_", "job_"))


def extract_task_ids(response: Any) -> list[str]:
    """Extract asynchronous APIMart ``task_id`` values from a response.

    APIMart responses have evolved over time — some variants put the task ID
    in ``data[i].task_id``, others put a top-level ``id`` field
    (``task_01KPW...``) alongside the standard ``data`` list of empty image
    placeholders. This function covers all known shapes:

    1. ``data[i].task_id`` — historical shape, kept for backward compat.
    2. ``data[i].id`` / ``data[i].request_id`` — LiteLLM sometimes forwards
       the async handle under the item itself.
    3. Top-level ``id`` / ``task_id`` / ``job_id`` / ``request_id`` on the
       response object — current APIMart shape when ``data`` is all-None.

    Any non-string or obviously unrelated ID (e.g. OpenAI ``chatcmpl-*``) is
    filtered out via :func:`_looks_like_apimart_task_id` to prevent bogus
    polling against ``/v1/tasks/{id}``.
    """
    response_dict = _to_plain_dict(response)
    data = response_dict.get("data", getattr(response, "data", None))
    task_ids: list[str] = []

    # ---- shape 1 & 2: per-item fields in data list ---------------------
    for item in _to_list(data):
        plain = _to_plain_dict(item)
        for key in _TASK_ID_CANDIDATE_KEYS:
            candidate = plain.get(key) or getattr(item, key, None)
            if isinstance(candidate, str) and candidate and _looks_like_apimart_task_id(candidate):
                task_ids.append(candidate)
                break  # one task_id per item

    # ---- shape 3: top-level fields on the response --------------------
    for key in _TASK_ID_CANDIDATE_KEYS:
        top = response_dict.get(key) or getattr(response, key, None)
        if isinstance(top, str) and _looks_like_apimart_task_id(top) and top not in task_ids:
            task_ids.append(top)

    # ---- shape 4 (last-resort): regex scan the whole serialized body ---
    # Some LiteLLM versions strip non-OpenAI fields from the Pydantic
    # ``ImageResponse`` (``id`` / ``task_id`` get dropped because they aren't
    # declared), so we also scan ``model_dump_json`` / ``repr`` as a fallback.
    # This is the "I don't care where it is, just find the task_XXX string"
    # safety net; duplicates are filtered by the set below.
    if not task_ids:
        blobs: list[str] = []
        if hasattr(response, "model_dump_json"):
            try:
                blobs.append(response.model_dump_json())
            except Exception:  # pragma: no cover - defensive
                pass
        hidden = getattr(response, "_hidden_params", None)
        if hidden:
            blobs.append(repr(hidden))
        headers = getattr(response, "_response_headers", None)
        if headers:
            blobs.append(repr(headers))
        try:
            blobs.append(repr(response))
        except Exception:  # pragma: no cover - defensive
            pass
        seen: set[str] = set()
        for blob in blobs:
            for match in _APIMART_TASK_ID_RE.findall(blob or ""):
                if match not in seen:
                    seen.add(match)
                    task_ids.append(match)
        if task_ids:
            logger.warning(
                "extract_task_ids used regex fallback to salvage task_id(s) from response body: {}",
                task_ids,
            )

    return task_ids


def extract_task_result_urls(task_payload: dict[str, Any]) -> list[str]:
    """Extract final image URLs from ``GET /tasks/{task_id}`` payloads."""
    data = task_payload.get("data", task_payload)
    if not isinstance(data, dict):
        return []

    result = data.get("result") or {}
    if not isinstance(result, dict):
        return []

    urls: list[str] = []
    for key in ("images", "image_urls", "urls"):
        if key in result:
            urls.extend(_extract_urls(result.get(key)))
    return urls


def extract_task_error_message(task_payload: dict[str, Any]) -> str | None:
    data = task_payload.get("data", task_payload)
    if not isinstance(data, dict):
        return None

    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    if isinstance(error, str) and error:
        return error
    return None


async def call_apimart_image_generation_raw(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str | None = None,
    quality: str | None = None,
    n: int = 1,
    extra_params: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Call APIMart ``POST /v1/images/generations`` directly via httpx.

    Why bypass LiteLLM for APIMart?
    ===============================
    LiteLLM's ``ImageResponse`` pydantic model only declares OpenAI-spec fields
    (``created`` / ``data[].url`` / ``data[].b64_json`` etc.). APIMart returns
    the async ``id="task_01..."`` at the **top level** of the response, which
    LiteLLM silently drops during deserialization. The consequence is
    ``extract_task_ids`` has nothing to find, poll never starts, user sees
    ``images=0`` even though APIMart generated the image.

    This helper issues the raw HTTP request and returns the parsed JSON
    body **as-is**, so the caller can access every field APIMart returned,
    including ``id`` and any future async-handle extensions.

    Parameters
    ----------
    base_url:
        APIMart base URL, e.g. ``https://api.apimart.ai/v1``. Trailing slash
        tolerated.
    api_key:
        Bearer token for ``Authorization`` header.
    model:
        Image model id (e.g. ``gpt-image-2``). **Without** any ``openai/`` or
        other provider prefix — pass the raw APIMart model name.
    prompt / size / quality / n:
        Standard image parameters. For APIMart ``gpt-image-2``, ``size`` is
        normalized to APIMart's ratio enum ("1:1", "9:16" etc.), ``n`` is
        forced to 1, and unsupported fields such as ``quality`` are omitted.
    extra_params:
        Additional body fields. For ``gpt-image-2`` only APIMart-supported
        keys (``image_urls`` / ``official_fallback``) are forwarded.
    timeout_seconds:
        Total HTTP timeout for this single POST.

    Returns
    -------
    dict
        Parsed JSON body. The caller must handle both "already has urls" and
        "only has task id → poll" scenarios using ``extract_inline_image_urls``
        and ``extract_task_ids`` from this same module.
    """
    if not is_apimart_base_url(base_url):
        raise ValueError("call_apimart_image_generation_raw requires an APIMart base URL")

    endpoint = f"{base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    requested_n = max(1, int(n))
    is_gpt_image_2 = _is_gpt_image_2(model)
    if is_gpt_image_2 and requested_n != 1:
        logger.warning(
            "APIMart gpt-image-2 supports n=1 only; requested n={}, using n=1",
            requested_n,
        )

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1 if is_gpt_image_2 else requested_n,
    }
    if size:
        normalized = normalize_apimart_size(size) or size
        if is_gpt_image_2 and not _is_supported_apimart_ratio(normalized):
            logger.warning(
                "APIMart gpt-image-2 unsupported size omitted: requested={}, normalized={}",
                size,
                normalized,
            )
        else:
            body["size"] = normalized

    if is_gpt_image_2:
        if quality:
            logger.warning(
                "APIMart gpt-image-2 does not support quality; dropping quality={}",
                quality,
            )

        supported_extra: dict[str, Any] = {}
        dropped_keys: list[str] = []
        for key, value in (extra_params or {}).items():
            if key in _GPT_IMAGE_2_EXTRA_KEYS:
                supported_extra[key] = value
            else:
                dropped_keys.append(key)

        if "image_urls" in supported_extra:
            image_urls = _normalize_image_urls(supported_extra["image_urls"])
            if len(image_urls) > 16:
                logger.warning(
                    "APIMart gpt-image-2 supports at most 16 image_urls; truncating {} -> 16",
                    len(image_urls),
                )
                image_urls = image_urls[:16]
            if image_urls:
                supported_extra["image_urls"] = image_urls
            else:
                supported_extra.pop("image_urls", None)

        if "official_fallback" in supported_extra:
            supported_extra["official_fallback"] = bool(supported_extra["official_fallback"])

        if dropped_keys:
            logger.warning(
                "APIMart gpt-image-2 unsupported image params dropped: {}",
                sorted(dropped_keys),
            )
        body.update(supported_extra)
    else:
        if quality:
            body["quality"] = quality
        if extra_params:
            body.update(extra_params)

    logger.info(
        "APIMart direct image generation: endpoint={}, model={}, size={}, n={}, body_keys={}",
        endpoint,
        model,
        body.get("size"),
        body["n"],
        sorted(body.keys()),
    )

    async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
        response = await client.post(endpoint, headers=headers, json=body)
        response.raise_for_status()
        return response.json()


async def wait_for_task_images(
    *,
    base_url: str,
    api_key: str,
    task_id: str,
    timeout_seconds: int | None = None,
    initial_delay_seconds: int | None = None,
    poll_interval_seconds: int | None = None,
) -> list[str]:
    """Poll APIMart task status until image URLs are available.

    All three timing parameters default to ``ai_config.image.apimart`` which
    is populated from ``settings.toml [ai.image.apimart]``. Callers may still
    override per-call (e.g. tests or one-off tuning), but production tuning
    belongs in the TOML file — **never hardcode new values here**.
    """
    if not is_apimart_base_url(base_url):
        raise ValueError("APIMart polling requires an APIMart base URL")

    default_initial, default_poll, default_timeout = _apimart_defaults()
    final_timeout = timeout_seconds if timeout_seconds is not None else default_timeout
    final_initial = initial_delay_seconds if initial_delay_seconds is not None else default_initial
    final_poll = poll_interval_seconds if poll_interval_seconds is not None else default_poll

    deadline = time.monotonic() + final_timeout
    endpoint = f"{base_url.rstrip('/')}/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    logger.info(
        "APIMart image task polling start: task_id={}, initial_delay={}s, poll_interval={}s, timeout={}s",
        task_id,
        final_initial,
        final_poll,
        final_timeout,
    )

    if final_initial > 0:
        await asyncio.sleep(final_initial)

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        while time.monotonic() < deadline:
            response = await client.get(
                endpoint,
                headers=headers,
                params={"language": "zh"},
            )
            response.raise_for_status()
            payload = response.json()

            urls = extract_task_result_urls(payload)
            if urls:
                elapsed = int(final_timeout - (deadline - time.monotonic()))
                logger.info(
                    "APIMart image task completed: task_id={}, urls={}, elapsed~={}s",
                    task_id,
                    len(urls),
                    elapsed,
                )
                return urls

            data = payload.get("data", payload)
            status = ""
            if isinstance(data, dict):
                status = str(data.get("status", "")).lower()

            if status in {"failed", "cancelled", "canceled"}:
                message = extract_task_error_message(payload) or "APIMart image task failed"
                raise RuntimeError(message)

            logger.debug(
                "APIMart image task still running: task_id={}, status={}",
                task_id,
                status or "unknown",
            )
            await asyncio.sleep(final_poll)

    raise TimeoutError(f"APIMart image task timed out: {task_id}")
