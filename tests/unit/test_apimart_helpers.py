"""Tests for `app.ai.providers.apimart` response extraction helpers.

Covers the three known APIMart response shapes for async image tasks so
future schema drift (new id field names) is caught before production.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.ai.providers.apimart import (
    call_apimart_image_generation_raw,
    extract_inline_image_urls,
    extract_task_ids,
    extract_task_result_urls,
    normalize_apimart_size,
)


class _SimpleResponse:
    """Minimal object that mimics an SDK response with attribute access."""

    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


# ---------- extract_inline_image_urls ------------------------------------


def test_extract_inline_image_urls_from_dict_response() -> None:
    response = {
        "data": [
            {"url": "https://cdn/a.png"},
            {"url": "https://cdn/b.png"},
        ]
    }
    assert extract_inline_image_urls(response) == [
        "https://cdn/a.png",
        "https://cdn/b.png",
    ]


def test_extract_inline_image_urls_ignores_none_urls() -> None:
    response = {"data": [{"url": None, "b64_json": None}]}
    assert extract_inline_image_urls(response) == []


# ---------- extract_task_result_urls -------------------------------------


def test_extract_task_result_urls_supports_gpt_image_2_docs_shape() -> None:
    payload = {
        "data": {
            "result": {
                "images": [
                    {"url": ["https://cdn.example.com/generated.png"]},
                ],
            }
        }
    }
    assert extract_task_result_urls(payload) == ["https://cdn.example.com/generated.png"]


# ---------- extract_task_ids --------------------------------------------


@pytest.mark.parametrize(
    "payload, expected",
    [
        # shape 1: per-item task_id (historical)
        (
            {"data": [{"task_id": "task_01ABCDEF"}]},
            ["task_01ABCDEF"],
        ),
        # shape 2a: per-item id field
        (
            {"data": [{"id": "task_01ZZZ"}]},
            ["task_01ZZZ"],
        ),
        # shape 2b: per-item request_id
        (
            {"data": [{"request_id": "job_req_xyz"}]},
            ["job_req_xyz"],
        ),
        # shape 3: top-level id (current APIMart behavior that broke prod)
        (
            {
                "id": "task_01KPW6VDQEB",
                "created": 123,
                "data": [{"url": None, "b64_json": None, "revised_prompt": None}],
            },
            ["task_01KPW6VDQEB"],
        ),
        # shape 3b: top-level task_id field
        (
            {"task_id": "task_99XYZ", "data": []},
            ["task_99XYZ"],
        ),
        # mixed: top-level id + per-item task_id → dedup
        (
            {
                "id": "task_same",
                "data": [{"task_id": "task_same"}],
            },
            ["task_same"],
        ),
    ],
)
def test_extract_task_ids_supports_all_known_shapes(payload: dict[str, object], expected: list[str]) -> None:
    assert extract_task_ids(payload) == expected


def test_extract_task_ids_filters_non_apimart_ids() -> None:
    """chatcmpl-* or arbitrary UUIDs must not trigger polling."""
    payload = {
        "id": "chatcmpl-123",
        "data": [{"id": "550e8400-e29b-41d4-a716-446655440000"}],
    }
    assert extract_task_ids(payload) == []


def test_extract_task_ids_from_attribute_object() -> None:
    """SDK pydantic objects expose fields via attributes; must still work."""
    response = _SimpleResponse(
        id="task_01SDK",
        data=[_SimpleResponse(url=None, b64_json=None, revised_prompt=None)],
    )
    assert extract_task_ids(response) == ["task_01SDK"]


def test_extract_task_ids_empty_on_plain_success() -> None:
    """If URLs are already returned inline, we should NOT return any task IDs
    (caller skips polling when URLs are present)."""
    response = {
        "data": [{"url": "https://cdn/a.png"}, {"url": "https://cdn/b.png"}],
    }
    assert extract_task_ids(response) == []


def test_extract_task_ids_regex_fallback_from_hidden_params() -> None:
    """P2-A7f: LiteLLM may strip top-level `id` from apimart responses when
    they aren't in the OpenAI schema. In that case the task_id survives in
    ``_hidden_params`` / ``_response_headers`` / the object repr. The regex
    fallback should be able to salvage it so we still can poll."""

    class _StrippedResponse:
        """Mimic LiteLLM ImageResponse that dropped the `id` field."""

        def __init__(self) -> None:
            self.data = [{"url": None, "b64_json": None, "revised_prompt": None}]
            self.created = 1776920690
            # Simulate apimart id hiding in LiteLLM _hidden_params (common)
            self._hidden_params = {"original_response": {"id": "task_01HIDDENTASK77"}}

        def model_dump_json(self) -> str:
            return '{"data": [{"url": null, "b64_json": null, "revised_prompt": null}], "created": 1776920690}'

        def model_dump(self) -> dict:
            return {
                "data": [{"url": None, "b64_json": None, "revised_prompt": None}],
                "created": 1776920690,
            }

    result = extract_task_ids(_StrippedResponse())
    # Must find the task_id hidden inside _hidden_params via regex
    assert "task_01HIDDENTASK77" in result


def test_extract_task_ids_regex_fallback_ignores_short_matches() -> None:
    """The regex fallback requires >=10 alnum chars after ``task_`` to avoid
    matching conversational noise like ``task_id`` in error strings."""

    class _BogusResponse:
        data = None
        # a literal "task_id" string should NOT be matched (too short)
        _hidden_params = {"debug": "the task_id field was not returned"}

        def model_dump_json(self) -> str:
            return '{"error": "task_id is required"}'

        def model_dump(self) -> dict:
            return {"error": "task_id is required"}

    assert extract_task_ids(_BogusResponse()) == []


# ---- call_apimart_image_generation_raw (P2-A7i direct http bypass) -------


@pytest.mark.asyncio
@respx.mock
async def test_call_apimart_image_generation_raw_returns_top_level_id() -> None:
    """Direct http call must surface the top-level ``id`` field that LiteLLM
    silently drops. This is the core of the P2-A7i bypass."""

    fake_body = {
        "id": "task_01ABCDEFGHIJK",
        "created": 1776923986,
        "data": [{"url": None, "b64_json": None, "revised_prompt": None}],
    }
    respx.post("https://api.apimart.ai/v1/images/generations").mock(return_value=httpx.Response(200, json=fake_body))

    raw = await call_apimart_image_generation_raw(
        base_url="https://api.apimart.ai/v1",
        api_key="sk-test",
        model="gpt-image-2",
        prompt="test prompt",
        size="1024x1024",
    )

    # Raw body preserved → id visible
    assert raw.get("id") == "task_01ABCDEFGHIJK"
    # And extract_task_ids can now pick it up
    assert extract_task_ids(raw) == ["task_01ABCDEFGHIJK"]


@pytest.mark.asyncio
async def test_call_apimart_image_generation_raw_rejects_non_apimart_url() -> None:
    """Safety: wrong base_url must raise, not silently POST elsewhere."""
    with pytest.raises(ValueError, match="APIMart base URL"):
        await call_apimart_image_generation_raw(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="gpt-image-2",
            prompt="hi",
        )


@pytest.mark.asyncio
@respx.mock
async def test_call_apimart_image_generation_raw_normalizes_size() -> None:
    """APIMart takes ratio strings (1:1, 9:16, ...) not WxH. Our helper must
    convert WxH → ratio before POST."""

    route = respx.post("https://api.apimart.ai/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"id": "task_01XXXXXXXXXXXX", "data": []})
    )

    await call_apimart_image_generation_raw(
        base_url="https://api.apimart.ai/v1/",
        api_key="sk",
        model="gpt-image-2",
        prompt="p",
        size="1024x1792",  # Should become "9:16"
    )

    # respx 捕获到了请求,检查 POST body
    assert route.called
    sent_body = route.calls[0].request.content.decode()
    assert '"size":"9:16"' in sent_body
    assert '"model":"gpt-image-2"' in sent_body
    assert '"prompt":"p"' in sent_body


@pytest.mark.asyncio
@respx.mock
async def test_call_apimart_image_generation_raw_filters_gpt_image_2_params() -> None:
    route = respx.post("https://api.apimart.ai/v1/images/generations").mock(
        return_value=httpx.Response(200, json={"id": "task_01PARAMCHECK", "data": []})
    )

    await call_apimart_image_generation_raw(
        base_url="https://api.apimart.ai/v1",
        api_key="sk",
        model="gpt-image-2",
        prompt="p",
        size="1024x2064",
        quality="standard",
        n=4,
        extra_params={
            "style": "natural",
            "response_format": "url",
            "official_fallback": 1,
            "image_urls": ["https://cdn.example.com/ref.png"],
        },
    )

    assert route.called
    sent_body = route.calls[0].request.content.decode()
    assert '"model":"gpt-image-2"' in sent_body
    assert '"prompt":"p"' in sent_body
    assert '"size":"1:2"' in sent_body
    assert '"n":1' in sent_body
    assert '"official_fallback":true' in sent_body
    assert '"image_urls":["https://cdn.example.com/ref.png"]' in sent_body
    assert '"quality"' not in sent_body
    assert '"style"' not in sent_body
    assert '"response_format"' not in sent_body


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("1024x2064", "1:2"),
        ("2064x1024", "2:1"),
        ("2064x2064", "1:1"),
        ("1024x3104", "9:21"),
        ("1040x1808", "9:16"),
    ],
)
def test_normalize_apimart_size_handles_batch_grid_gap_sizes(
    size: str,
    expected: str,
) -> None:
    assert normalize_apimart_size(size) == expected
