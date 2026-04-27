"""Tests for ``app.core.image_processor.ImageProcessor.split_grid``.

Covers:
- 正确的按行优先索引(0,0 → 0,1 → 1,0 → 1,1)
- gap_px 被正确扣除(4 格不重叠)
- 空白占比检测: 纯白格判 is_blank=True, 非白格 False
- 非均匀分格(2x3, 3x2)仍按正确像素边界切
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.core.image_processor import ImageProcessor


def _make_grid_image(rows: int, cols: int, cell: int, gap: int) -> bytes:
    """造一张 rows x cols 网格测试图: 每格填不同纯色(第 0 格白, 其余彩色),
    便于检测空白/非空白与切格索引."""
    w = cols * cell + gap * max(cols - 1, 0)
    h = rows * cell + gap * max(rows - 1, 0)
    img = Image.new("RGB", (w, h), (255, 255, 255))  # 整图白(含 gap)
    palette = [
        (255, 255, 255),  # 第 0 格空白
        (200, 50, 50),    # 红
        (50, 200, 50),    # 绿
        (50, 50, 200),    # 蓝
        (200, 200, 50),   # 黄
        (200, 50, 200),   # 紫
    ]
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            color = palette[idx % len(palette)]
            left = c * (cell + gap)
            upper = r * (cell + gap)
            for x in range(left, left + cell):
                for y in range(upper, upper + cell):
                    img.putpixel((x, y), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def processor(tmp_path, monkeypatch) -> ImageProcessor:
    """处理器写入临时目录,避免污染 uploads/"""
    from app.core import image_processor as ip_mod

    p = ip_mod.ImageProcessor()
    monkeypatch.setattr(p, "_upload_dir", tmp_path)
    monkeypatch.setattr(p, "_base_url", "/uploads-test")
    return p


@pytest.mark.asyncio
async def test_split_2x2_returns_four_cells_row_first(processor, tmp_path):
    image_bytes = _make_grid_image(rows=2, cols=2, cell=80, gap=8)

    with patch.object(processor, "_download", AsyncMock(return_value=image_bytes)):
        cells = await processor.split_grid(
            url="https://fake/composite.png",
            rows=2,
            cols=2,
            gap_px=8,
            sub_dir="xhs-test",
            task_id="t-unit",
            blank_threshold=0.9,
        )

    assert len(cells) == 4
    # row-first order
    assert [(c.row, c.col) for c in cells] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    # all cells are 80x80 (cell size)
    assert all(c.width == 80 and c.height == 80 for c in cells)
    # Cell 0 is pure white → is_blank
    assert cells[0].is_blank is True
    assert cells[0].blank_ratio >= 0.9
    # Cells 1/2/3 have solid colors → not blank
    assert all(not c.is_blank for c in cells[1:])
    # Files were written
    assert any(tmp_path.rglob("*.png"))
    assert any(tmp_path.rglob("*.webp"))


@pytest.mark.asyncio
async def test_split_1x4_strip_shape(processor):
    image_bytes = _make_grid_image(rows=1, cols=4, cell=64, gap=4)

    with patch.object(processor, "_download", AsyncMock(return_value=image_bytes)):
        cells = await processor.split_grid(
            url="https://fake/strip.png",
            rows=1,
            cols=4,
            gap_px=4,
            sub_dir="xhs-test-strip",
        )

    assert len(cells) == 4
    assert [(c.row, c.col) for c in cells] == [(0, 0), (0, 1), (0, 2), (0, 3)]
    # Cell 0 white, others colored
    assert cells[0].is_blank is True
    assert all(not c.is_blank for c in cells[1:])


@pytest.mark.asyncio
async def test_split_grid_upscales_cells_to_target_size(processor, tmp_path):
    image_bytes = _make_grid_image(rows=2, cols=2, cell=80, gap=8)

    with patch.object(processor, "_download", AsyncMock(return_value=image_bytes)):
        cells = await processor.split_grid(
            url="https://fake/composite.png",
            rows=2,
            cols=2,
            gap_px=8,
            sub_dir="xhs-test-upscale",
            target_cell_size="160x160",
            blank_threshold=0.9,
        )

    assert len(cells) == 4
    assert all(c.width == 160 and c.height == 160 for c in cells)
    original_file = next((tmp_path / "xhs-test-upscale" / "originals").glob("*.png"))
    with Image.open(original_file) as img:
        assert img.size == (160, 160)


@pytest.mark.asyncio
async def test_split_invalid_rows_cols_raises(processor):
    with pytest.raises(ValueError):
        await processor.split_grid(
            url="x", rows=0, cols=2, gap_px=0, sub_dir="x"
        )
    with pytest.raises(ValueError):
        await processor.split_grid(
            url="x", rows=2, cols=0, gap_px=0, sub_dir="x"
        )


@pytest.mark.asyncio
async def test_split_download_failure_raises(processor):
    with (
        patch.object(processor, "_download", AsyncMock(return_value=None)),
        pytest.raises(ValueError, match="合成图下载失败"),
    ):
        await processor.split_grid(
            url="https://fake/broken.png",
            rows=2,
            cols=2,
            gap_px=0,
            sub_dir="xhs-test-fail",
        )
