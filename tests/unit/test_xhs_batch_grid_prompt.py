"""Tests for `XHSImageService._build_batch_grid_prompt` length budget.

Guards the 4000-char hard cap of ``ImageRequest.prompt.max_length`` with two
layered budgets introduced in P2-A7h:
- per-cell content truncation (``_BATCH_GRID_CELL_CONTENT_MAX_LEN``)
- final composed prompt truncation (``_BATCH_GRID_PROMPT_MAX_LEN``)
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.ai.services.xhs.image as xhs_image_module
from app.ai.services.xhs.image import XHSImageService
from app.ai.services.xhs.schemas import XHSPage
from app.core.image_processor import GridCell


@pytest.mark.asyncio
async def test_build_batch_grid_prompt_under_4000_chars_for_long_input():
    """When every page ships a very long image_prompt, the final composed
    prompt must stay under 4000 chars (ImageRequest limit)."""
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content="content " * 20,
            page_type="content",
            # 2000-char image_prompt per page → 4 pages × 2000 = 8000 chars
            # of per-page text alone, way over the 4000 limit.
            image_prompt="很长的图片提示词描述内容" * 100,
        )
        for i in range(1, 5)
    ]

    composed = await svc._build_batch_grid_prompt(
        pages=pages,
        outline="",
        user_topic="测试",
        rows=2,
        cols=2,
        gap_px=16,
        style_prompt="粉色医疗风",
        negative_style_prompt="禁止黑白",
        user_id=None,
    )

    assert len(composed) <= 3900, f"composed prompt must stay within the 3900 safety margin, got {len(composed)}"


@pytest.mark.asyncio
async def test_build_batch_grid_prompt_preserves_short_content():
    """Short inputs should pass through untouched (no ellipsis)."""
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content="",
            page_type="content",
            image_prompt=f"短的描述 {i}",
        )
        for i in range(1, 5)
    ]
    composed = await svc._build_batch_grid_prompt(
        pages=pages,
        outline="",
        user_topic="测试",
        rows=2,
        cols=2,
        gap_px=16,
        style_prompt="粉色",
        negative_style_prompt=None,
        user_id=None,
    )
    # Short content preserved in full
    for i in range(1, 5):
        assert f"短的描述 {i}" in composed
    # No ellipsis triggered
    assert "…" not in composed


def test_truncate_preserving_end_basic():
    """Unit-level check of the static truncation helper."""
    text = "abcdefghijklmnopqrstuvwxyz"
    assert XHSImageService._truncate_preserving_end(text, 100) == text
    truncated = XHSImageService._truncate_preserving_end(text, 10)
    assert truncated.endswith("…")
    assert len(truncated) == 10
    # Zero-budget edge
    assert XHSImageService._truncate_preserving_end("abc", 1) == "…"


def test_apply_style_constraints_forbids_page_markers():
    prompt = XHSImageService._apply_style_constraints(
        "9:16 Xiaohongshu content slide",
        style_prompt=None,
        negative_style_prompt=None,
    )

    assert "画面页码禁令" in prompt
    assert "1/4" in prompt
    assert "完全无页码" in prompt


@pytest.mark.asyncio
async def test_build_batch_grid_prompt_adds_blank_unused_cells():
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content="content",
            page_type="content",
            image_prompt=f"prompt {i}",
        )
        for i in range(2)
    ]

    composed = await svc._build_batch_grid_prompt(
        pages=pages,
        outline="",
        user_topic="测试",
        rows=2,
        cols=2,
        gap_px=16,
        style_prompt=None,
        negative_style_prompt=None,
        user_id=None,
    )

    assert "UNUSED CELL" in composed
    assert '"index": 4' in composed
    assert "NO PAGE MARKERS" in composed


def test_pick_subset_grid_uses_vertical_2x2_contact_sheet():
    assert XHSImageService._pick_subset_grid(2) == (2, 2)
    assert XHSImageService._pick_subset_grid(3) == (2, 2)
    assert XHSImageService._pick_subset_grid(4) == (2, 2)


@pytest.mark.asyncio
async def test_generate_images_batch_grid_splits_six_pages_into_two_api_calls(monkeypatch):
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content=f"content {i}",
            page_type="content",
            image_prompt=f"prompt {i}",
        )
        for i in range(6)
    ]

    image_calls: list[str] = []
    split_calls: list[str] = []
    split_target_sizes: list[str | None] = []

    async def fake_image_generate(**kwargs):
        image_calls.append(kwargs["prompt"])
        return SimpleNamespace(
            images=[
                SimpleNamespace(
                    url=f"https://cdn.example.com/composite-{len(image_calls)}.png",
                )
            ]
        )

    async def fake_split_grid(**kwargs):
        split_calls.append(kwargs["url"])
        split_target_sizes.append(kwargs.get("target_cell_size"))
        return [
            GridCell(
                index=i,
                row=i // 2,
                col=i % 2,
                original_url=f"/uploads/xhs/originals/b{len(split_calls)}-{i}.png",
                thumbnail_url=f"/uploads/xhs/thumbnails/b{len(split_calls)}-{i}.webp",
                width=512,
                height=896,
                original_size=100,
                thumbnail_size=50,
                is_blank=False,
                blank_ratio=0.0,
            )
            for i in range(4)
        ]

    monkeypatch.setattr(xhs_image_module.ai, "image_generate", fake_image_generate)
    monkeypatch.setattr(xhs_image_module.image_processor, "split_grid", fake_split_grid)

    events = [
        event
        async for event in svc.generate_images_batch_grid(
            pages=pages,
            outline="",
            user_topic="测试",
            style_prompt=None,
            negative_style_prompt=None,
        )
    ]

    page_done = [event for event in events if event["event"] == "page_done"]
    done = next(event for event in events if event["event"] == "done")

    assert len(image_calls) == 2
    assert len(split_calls) == 2
    expected_target = xhs_image_module.ai_config.image.batch_grid.split_target_cell_size
    assert all(size == expected_target for size in split_target_sizes)
    assert sorted(event["data"]["index"] for event in page_done) == [0, 1, 2, 3, 4, 5]
    assert done["data"]["success"] == 6
    assert done["data"]["failed"] == 0
    assert done["data"]["api_calls"] == 2


@pytest.mark.asyncio
async def test_generate_images_batch_grid_runs_two_batches_concurrently(monkeypatch):
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content=f"content {i}",
            page_type="content",
            image_prompt=f"prompt {i}",
        )
        for i in range(8)
    ]

    active_calls = 0
    max_active_calls = 0
    started_calls = 0
    first_two_started = asyncio.Event()

    async def fake_image_generate(**kwargs):
        nonlocal active_calls, max_active_calls, started_calls
        active_calls += 1
        started_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        if started_calls == 2:
            first_two_started.set()
        await asyncio.wait_for(first_two_started.wait(), timeout=1)
        active_calls -= 1
        return SimpleNamespace(
            images=[
                SimpleNamespace(
                    url=f"https://cdn.example.com/composite-{started_calls}.png",
                )
            ]
        )

    async def fake_split_grid(**kwargs):
        return [
            GridCell(
                index=i,
                row=i // 2,
                col=i % 2,
                original_url=f"/uploads/xhs/originals/{kwargs['filename_prefix']}{i}.png",
                thumbnail_url=f"/uploads/xhs/thumbnails/{kwargs['filename_prefix']}{i}.webp",
                width=512,
                height=896,
                original_size=100,
                thumbnail_size=50,
                is_blank=False,
                blank_ratio=0.0,
            )
            for i in range(4)
        ]

    monkeypatch.setattr(xhs_image_module.ai, "image_generate", fake_image_generate)
    monkeypatch.setattr(xhs_image_module.image_processor, "split_grid", fake_split_grid)

    events = [
        event
        async for event in svc.generate_images_batch_grid(
            pages=pages,
            outline="",
            user_topic="test",
            style_prompt=None,
            negative_style_prompt=None,
        )
    ]

    done = next(event for event in events if event["event"] == "done")
    assert max_active_calls == 2
    assert done["data"]["success"] == 8
    assert done["data"]["failed"] == 0


@pytest.mark.asyncio
async def test_generate_images_batch_grid_can_disable_split_upscale(monkeypatch):
    svc = XHSImageService()
    pages = [
        XHSPage(
            index=i,
            content=f"content {i}",
            page_type="content",
            image_prompt=f"prompt {i}",
        )
        for i in range(2)
    ]

    split_target_sizes: list[str | None] = []

    async def fake_image_generate(**kwargs):
        return SimpleNamespace(
            images=[SimpleNamespace(url="https://cdn.example.com/composite.png")]
        )

    async def fake_split_grid(**kwargs):
        split_target_sizes.append(kwargs.get("target_cell_size"))
        return [
            GridCell(
                index=i,
                row=i // 2,
                col=i % 2,
                original_url=f"/uploads/xhs/originals/{i}.png",
                thumbnail_url=f"/uploads/xhs/thumbnails/{i}.webp",
                width=512,
                height=896,
                original_size=100,
                thumbnail_size=50,
                is_blank=False,
                blank_ratio=0.0,
            )
            for i in range(4)
        ]

    monkeypatch.setattr(xhs_image_module.ai, "image_generate", fake_image_generate)
    monkeypatch.setattr(xhs_image_module.image_processor, "split_grid", fake_split_grid)

    events = [
        event
        async for event in svc.generate_images_batch_grid(
            pages=pages,
            outline="",
            user_topic="test",
            style_prompt=None,
            negative_style_prompt=None,
            split_upscale_enabled=False,
        )
    ]

    done = next(event for event in events if event["event"] == "done")
    assert split_target_sizes == [None]
    assert done["data"]["success"] == 2


@pytest.mark.asyncio
async def test_generate_images_batch_grid_keeps_single_page_on_per_page(monkeypatch):
    svc = XHSImageService()
    page = XHSPage(
        index=0,
        content="content",
        page_type="cover",
        image_prompt="prompt",
    )

    async def fake_generate_images_stream(**kwargs):
        yield {
            "event": "done",
            "data": {
                "task_id": "per_page_task",
                "total": len(kwargs["pages"]),
                "success": 1,
                "failed": 0,
            },
        }

    monkeypatch.setattr(svc, "generate_images_stream", fake_generate_images_stream)

    events = [
        event
        async for event in svc.generate_images_batch_grid(
            pages=[page],
            outline="",
            user_topic="测试",
            style_prompt=None,
            negative_style_prompt=None,
        )
    ]

    assert events[0]["event"] == "mode_fallback"
    assert events[0]["data"]["reason"] == "single page uses per_page"
    assert events[-1]["event"] == "done"
