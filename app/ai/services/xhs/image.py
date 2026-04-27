"""XHS image generation service."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncIterator, List, Optional

from app.ai.config import ai_config
from app.ai.facade import ai
from app.ai.prompts import prompts
from app.ai.services.xhs.schemas import XHSPage
from app.ai.services.xhs.utils import normalize_page_type, page_type_to_cn
from app.core.image_processor import GridCell, image_processor
from app.core.logger import logger

DEFAULT_XHS_SIZE = "1024x1792"
DEFAULT_XHS_GRID_CELL_SIZE = "512x896"

NO_PAGE_MARKER_CONSTRAINT = (
    "\n\n【画面页码禁令 · 必须严格遵守】\n"
    "不要在图片里绘制页码、序号、轮播角标、进度点或任何类似 1/4、2/4、"
    "第1页、Page 1、P1 的页面编号。后续可能重新排序,画面本身必须完全无页码。"
)


def _as_optional_bool(value) -> Optional[bool]:
    """Parse optional bool values from JSON-ish grid_config."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


class XHSImageService:
    """Generate and post-process Xiaohongshu images page by page."""

    async def generate_images_stream(
        self,
        pages: List[XHSPage],
        outline: str,
        user_topic: str,
        images: Optional[List[str]] = None,
        image_size: Optional[str] = None,
        image_quality: Optional[str] = None,
        image_style: Optional[str] = None,
        image_engine: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        extra_params: Optional[dict] = None,
        images_per_page: int = 1,
        user_id: Optional[int] = None,
        style_prompt: Optional[str] = None,
        negative_style_prompt: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        total = len(pages)

        if total == 0:
            yield {
                "event": "done",
                "data": {"task_id": task_id, "total": 0, "success": 0, "failed": 0},
            }
            return

        yield {
            "event": "progress",
            "data": {
                "task_id": task_id,
                "total": total,
                "completed": 0,
                "current": "正在准备生成...",
            },
        }

        cover_page = next(
            (page for page in pages if normalize_page_type(page.page_type) == "cover"),
            None,
        )
        other_pages = [page for page in pages if normalize_page_type(page.page_type) != "cover"]

        content_semaphore = asyncio.Semaphore(ai_config.xhs.max_concurrency)
        result_queue: asyncio.Queue = asyncio.Queue()
        bg_tasks: list[asyncio.Task] = []
        completed = 0

        async def generate_single_page(page: XHSPage, *, is_cover: bool = False) -> None:
            semaphore = asyncio.Semaphore(1) if is_cover else content_semaphore
            async with semaphore:
                page_type = normalize_page_type(page.page_type)
                label = "cover" if is_cover else f"page-{page.index}"

                await result_queue.put(
                    {
                        "event": "page_start",
                        "data": {
                            "index": page.index,
                            "page_type": page_type,
                            "status": "running",
                            "task_id": task_id,
                        },
                    }
                )

                try:
                    logger.info("Generating XHS {} image", label)
                    prompt = await self._build_image_prompt(
                        page=page,
                        outline=outline,
                        user_topic=user_topic,
                        user_id=user_id,
                        style_prompt=style_prompt,
                        negative_style_prompt=negative_style_prompt,
                    )

                    image_result = await self._generate_page_image(
                        prompt=prompt,
                        images=images,
                        image_size=image_size,
                        image_quality=image_quality,
                        image_style=image_style,
                        image_engine=image_engine,
                        negative_prompt=negative_prompt,
                        extra_params=extra_params,
                        images_per_page=images_per_page,
                    )

                    first_image = image_result.images[0] if image_result.images else None
                    ai_url = first_image.url if first_image else None
                    if not ai_url:
                        raise ValueError("AI did not return an image URL")

                    await result_queue.put(
                        {
                            "event": "page_done",
                            "data": {
                                "index": page.index,
                                "page_type": page_type,
                                "task_id": task_id,
                                "status": "success",
                                "thumbnail_url": ai_url,
                                "original_url": ai_url,
                                "url": ai_url,
                            },
                            "_count_success": True,
                        }
                    )

                    async def bg_process() -> None:
                        try:
                            result_data = await self._process_image(
                                ai_url=ai_url,
                                page=page,
                                task_id=task_id,
                                page_type=page_type,
                            )
                            result_data["status"] = "processed"
                            await result_queue.put({"event": "page_updated", "data": result_data})
                        except Exception as exc:
                            logger.warning(
                                "Background image processing failed for page {}: {}",
                                page.index,
                                exc,
                            )

                    bg_tasks.append(asyncio.create_task(bg_process()))
                except Exception as exc:
                    logger.error("Failed to generate XHS page image {}: {}", label, exc)
                    await result_queue.put(
                        {
                            "event": "page_error",
                            "data": {
                                "index": page.index,
                                "status": "failed",
                                "error": str(exc),
                                "page_type": page_type,
                                "task_id": task_id,
                            },
                        }
                    )

        all_tasks: list[asyncio.Task] = []
        if cover_page is not None:
            all_tasks.append(asyncio.create_task(generate_single_page(cover_page, is_cover=True)))
        for page in other_pages:
            all_tasks.append(asyncio.create_task(generate_single_page(page)))

        finished_count = 0
        total_tasks = len(all_tasks)

        while finished_count < total_tasks or not result_queue.empty():
            try:
                result = await asyncio.wait_for(result_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                done_tasks = sum(1 for task in all_tasks if task.done())
                if done_tasks >= total_tasks and result_queue.empty():
                    break
                continue

            event_type = result["event"]
            if event_type in {"page_done", "page_error"}:
                finished_count += 1
                if result.pop("_count_success", False):
                    completed += 1

            yield result

            if event_type in {"page_done", "page_error"}:
                yield {
                    "event": "progress",
                    "data": {
                        "task_id": task_id,
                        "total": total,
                        "completed": completed,
                        "current": f"已完成 {completed}/{total}",
                    },
                }

        await asyncio.gather(*all_tasks, return_exceptions=True)

        if bg_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*bg_tasks, return_exceptions=True),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for background XHS image processing")

            while not result_queue.empty():
                yield result_queue.get_nowait()

        yield {
            "event": "done",
            "data": {
                "task_id": task_id,
                "total": total,
                "success": completed,
                "failed": total - completed,
                "message": "全部完成",
            },
        }

    async def _generate_page_image(
        self,
        *,
        prompt: str,
        images: Optional[List[str]],
        image_size: Optional[str],
        image_quality: Optional[str],
        image_style: Optional[str],
        image_engine: Optional[str],
        negative_prompt: Optional[str],
        extra_params: Optional[dict],
        images_per_page: int,
    ):
        gen_size = image_size or self._get_image_size()
        gen_quality = image_quality or ai_config.image.default_quality
        extra_kwargs = self._build_image_kwargs(images)
        request_extra_params = dict(extra_params or {})
        if image_style:
            extra_kwargs["style"] = image_style

        async def once():
            return await ai.image_generate(
                prompt=prompt,
                model=image_engine,
                size=gen_size,
                quality=gen_quality,
                negative_prompt=negative_prompt,
                extra_params=request_extra_params or None,
                **extra_kwargs,
            )

        if images_per_page <= 1:
            return await once()

        results = await asyncio.gather(
            *(once() for _ in range(images_per_page)),
            return_exceptions=True,
        )
        for result in results:
            if not isinstance(result, Exception) and result.images and result.images[0].url:
                return result
        raise ValueError(f"All {images_per_page} candidate image generations failed")

    async def _process_image(
        self,
        ai_url: str,
        page: XHSPage,
        task_id: str,
        page_type: str,
    ) -> dict:
        """Download, thumbnail, and persist generated images locally."""
        try:
            from app.core.image_processor import image_processor

            result = await image_processor.process(
                url=ai_url,
                sub_dir="xhs",
                task_id=task_id,
                filename_prefix=f"p{page.index}_",
            )

            return {
                "index": page.index,
                "page_type": page_type,
                "task_id": task_id,
                "status": "success",
                "url": result.original_url,
                "image_url": result.original_url,
                "thumbnail_url": result.thumbnail_url,
                "original_url": result.original_url,
                "width": result.width,
                "height": result.height,
                "original_size": result.original_size,
                "thumbnail_size": result.thumbnail_size,
            }
        except Exception as exc:
            logger.warning(
                "Image post-processing failed, falling back to upstream URL: {}",
                exc,
            )
            return {
                "index": page.index,
                "page_type": page_type,
                "task_id": task_id,
                "status": "success",
                "url": ai_url,
                "image_url": ai_url,
                "thumbnail_url": ai_url,
                "original_url": ai_url,
                "width": 0,
                "height": 0,
                "original_size": 0,
                "thumbnail_size": 0,
            }

    async def _build_image_prompt(
        self,
        page: XHSPage,
        outline: str,
        user_topic: str,
        user_id: int | None = None,
        style_prompt: Optional[str] = None,
        negative_style_prompt: Optional[str] = None,
    ) -> str:
        """Build the final image prompt for one XHS page.

        When the frontend has pre-generated an ``image_prompt`` (typically via
        ``/xhs/prompts``), we still append the template's ``style_prompt`` /
        ``negative_style_prompt`` as a hard, last-mile constraint. This is
        what makes "switching templates" visibly change the generated image
        even though the per-page prompt itself was already written upstream.
        """
        if page.image_prompt:
            return self._apply_style_constraints(page.image_prompt, style_prompt, negative_style_prompt)

        page_type = normalize_page_type(page.page_type)
        variables = {
            "page_content": page.content,
            "page_type": page_type_to_cn(page_type),
            "full_outline": outline,
            "user_topic": user_topic or "",
        }

        full_prompt = await prompts.get("xhs/image_full", variables, user_id=user_id)
        short_prompt = await prompts.get(
            "xhs/image_short",
            variables,
            fallback=None,
            user_id=user_id,
        )

        if not full_prompt:
            fallback = page.content
        elif short_prompt and len(full_prompt) > ai_config.xhs.short_prompt_threshold:
            fallback = short_prompt
        else:
            fallback = full_prompt

        return self._apply_style_constraints(fallback, style_prompt, negative_style_prompt)

    @staticmethod
    def _apply_style_constraints(
        base_prompt: str,
        style_prompt: Optional[str],
        negative_style_prompt: Optional[str],
    ) -> str:
        """Append template-level style/negative constraints to a page prompt.

        The constraints are suffixed (not prefixed) so the page-specific
        content still anchors the composition, while the template style
        dictates look & feel. Strong wording is used so the image model
        treats them as must-follow rules rather than suggestions.
        """
        parts: list[str] = [base_prompt]
        if style_prompt and style_prompt.strip():
            parts.append(
                "\n\n【风格统一要求 · 必须严格遵守】\n"
                f"{style_prompt.strip()}\n"
                "以上风格为本次输出的硬性约束,任何元素,配色,版式,字体层级与材质"
                "质感都必须贴合,不得偏离或自行替换为其他风格。"
            )
        if negative_style_prompt and negative_style_prompt.strip():
            parts.append(
                f"\n\n【绝对禁止出现】\n{negative_style_prompt.strip()}\n以上元素在任何情况下都不得出现在画面中。"
            )
        parts.append(NO_PAGE_MARKER_CONSTRAINT)
        return "".join(parts)

    def _build_image_kwargs(self, images: Optional[List[str]]) -> dict:
        """Build provider-specific extra kwargs for image generation."""
        if not images:
            return {}

        provider_name = ai.provider.name
        if provider_name in {"nanpro", "image_api"}:
            return {"reference_images": images}

        return {}

    def _get_image_size(self) -> str:
        """Return the default XHS-friendly image size."""
        if ai_config.image.default_size and ai_config.image.default_size != "1024x1024":
            return ai_config.image.default_size
        return DEFAULT_XHS_SIZE

    # ==================================================================
    #                       batch_grid (省钱模式)
    # ==================================================================

    async def generate_images_batch_grid(
        self,
        pages: List[XHSPage],
        outline: str,
        user_topic: str,
        *,
        rows: Optional[int] = None,
        cols: Optional[int] = None,
        cell_size: Optional[str] = None,
        gap_px: Optional[int] = None,
        split_upscale_enabled: Optional[bool] = None,
        split_target_cell_size: Optional[str] = None,
        image_engine: Optional[str] = None,
        image_quality: Optional[str] = None,
        image_style: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        extra_params: Optional[dict] = None,
        style_prompt: Optional[str] = None,
        negative_style_prompt: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> AsyncIterator[dict]:
        """一次 API 生成 rows x cols 网格合成图 + Pillow 切割成独立页。

        事件格式与 ``generate_images_stream`` 一致,前端 SSE 处理逻辑不用改:
        ``progress`` / ``page_start`` / ``page_done`` / ``page_error`` / ``done``;
        额外一种: ``mode_fallback`` (降级回 per_page 时先推一次, 让前端能在
        UI 上提示"本次因 xxx 降级到逐页模式")。

        多页时会按单个网格容量分批处理。例如默认 2x2 下,
        6 页会拆成 4 + 2, 共 2 次图片 API, 每批未用 cell 留白。

        降级触发:
          1. ``ai_config.image.batch_grid.enabled == False``
          2. 单页请求 (逐页生成质量更稳, 成本相同)
          3. 网格配置无效
          4. 合成图像素数 > ``max_pixels``
          5. ``image_engine`` 不在 ``supported_models`` 白名单
        发生降级时事件流改走 :meth:`generate_images_stream`, 先推一条
        ``{event:"mode_fallback", data:{reason:"..."}}`` 让前端知道原因。
        """
        cfg = ai_config.image.batch_grid
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        total = len(pages)

        final_rows = int(rows if rows is not None else cfg.default_rows)
        final_cols = int(cols if cols is not None else cfg.default_cols)
        final_gap = int(gap_px if gap_px is not None else cfg.grid_gap_px)
        final_cell_size = str(cell_size or cfg.default_cell_size)
        requested_split_upscale = _as_optional_bool(split_upscale_enabled)
        final_split_upscale_enabled = (
            cfg.split_upscale_enabled
            if requested_split_upscale is None
            else requested_split_upscale
        )
        final_split_target_cell_size = str(
            split_target_cell_size or cfg.split_target_cell_size
        )
        effective_split_target_cell_size = (
            final_split_target_cell_size if final_split_upscale_enabled else None
        )
        try:
            cell_w_str, cell_h_str = final_cell_size.lower().split("x")
            cell_w = int(cell_w_str)
            cell_h = int(cell_h_str)
        except Exception:
            cell_w, cell_h = 1024, 1024
        composite_w = cell_w * final_cols + final_gap * max(final_cols - 1, 0)
        composite_h = cell_h * final_rows + final_gap * max(final_rows - 1, 0)
        composite_size = f"{composite_w}x{composite_h}"
        # cell_pixels_total 是"4 个单格独立像素数之和"(不含 gap),真正反映成本约束;
        # composite_pixels 是"含 gap 的合成图像素数",只用在日志里辅助观察。
        # gap_px=16 会让 2x2+1024 单格的合成图从 2048² 变成 2064² = 4,260,096,
        # 用 composite_pixels 会在边界情况误伤;所以以 cell_pixels_total 为准。
        cell_pixels_total = cell_w * cell_h * final_cols * final_rows
        resolved_engine = image_engine or ai_config.image.default_model
        grid_capacity = final_rows * final_cols
        pages_per_batch = min(int(cfg.max_pages_per_grid), grid_capacity)

        fallback_reason: Optional[str] = None
        if not cfg.enabled:
            fallback_reason = "batch_grid disabled in settings.toml"
        elif total == 0:
            fallback_reason = "no pages to render"
        elif total == 1:
            fallback_reason = "single page uses per_page"
        elif grid_capacity <= 0 or pages_per_batch <= 0:
            fallback_reason = f"invalid batch_grid layout rows={final_rows}, cols={final_cols}"
        elif cell_pixels_total > cfg.max_pixels:
            fallback_reason = (
                f"cell_pixels_total {cell_pixels_total} (cells: "
                f"{final_rows}x{final_cols}x{cell_w}x{cell_h}) > "
                f"max_pixels={cfg.max_pixels}"
            )
        elif cfg.supported_models and resolved_engine not in cfg.supported_models:
            fallback_reason = f"model '{resolved_engine}' not in batch_grid.supported_models"

        if fallback_reason:
            logger.warning(
                "batch_grid fallback -> per_page: {}. task_id={}",
                fallback_reason,
                task_id,
            )
            yield {
                "event": "mode_fallback",
                "data": {
                    "task_id": task_id,
                    "from": "batch_grid",
                    "to": "per_page",
                    "reason": fallback_reason,
                },
            }
            async for event in self.generate_images_stream(
                pages=pages,
                outline=outline,
                user_topic=user_topic,
                image_size=cell_size,
                image_quality=image_quality,
                image_style=image_style,
                image_engine=image_engine,
                negative_prompt=negative_prompt,
                extra_params=extra_params,
                user_id=user_id,
                style_prompt=style_prompt,
                negative_style_prompt=negative_style_prompt,
            ):
                yield event
            return

        page_batches = [
            pages[start : start + pages_per_batch]
            for start in range(0, total, pages_per_batch)
        ]
        batch_total = len(page_batches)
        if batch_total > 1:
            logger.info(
                "batch_grid split into {} batches: task_id={}, total_pages={}, pages_per_batch={}, grid={}x{}",
                batch_total,
                task_id,
                total,
                pages_per_batch,
                final_rows,
                final_cols,
            )

        yield {
            "event": "progress",
            "data": {
                "task_id": task_id,
                "total": total,
                "completed": 0,
                "api_calls": batch_total,
                "current": (
                    f"准备分 {batch_total} 批合成 {final_rows}x{final_cols} 网格图..."
                    if batch_total > 1
                    else f"准备合成 {final_rows}x{final_cols} 网格大图..."
                ),
            },
        }
        for page in pages:
            yield {
                "event": "page_start",
                "data": {
                    "index": page.index,
                    "page_type": normalize_page_type(page.page_type),
                    "status": "running",
                    "task_id": task_id,
                },
            }

        if batch_total > 1:
            async for event in self._generate_batch_grid_batches_concurrent(
                task_id=task_id,
                page_batches=page_batches,
                total=total,
                final_rows=final_rows,
                final_cols=final_cols,
                final_gap=final_gap,
                composite_size=composite_size,
                resolved_engine=resolved_engine,
                image_quality=image_quality,
                negative_prompt=negative_prompt,
                extra_params=extra_params,
                outline=outline,
                user_topic=user_topic,
                style_prompt=style_prompt,
                negative_style_prompt=negative_style_prompt,
                user_id=user_id,
                blank_threshold=cfg.blank_threshold,
                split_target_cell_size=effective_split_target_cell_size,
            ):
                yield event
            return

        completed = 0
        failed = 0
        for batch_index, batch_pages in enumerate(page_batches, start=1):
            composed_prompt = await self._build_batch_grid_prompt(
                pages=batch_pages,
                outline=outline,
                user_topic=user_topic,
                rows=final_rows,
                cols=final_cols,
                gap_px=final_gap,
                style_prompt=style_prompt,
                negative_style_prompt=negative_style_prompt,
                user_id=user_id,
            )

            try:
                logger.info(
                    "batch_grid API call start: task_id={}, batch={}/{}, pages={}, size={}, model={}",
                    task_id,
                    batch_index,
                    batch_total,
                    [page.index for page in batch_pages],
                    composite_size,
                    resolved_engine,
                )
                yield {
                    "event": "progress",
                    "data": {
                        "task_id": task_id,
                        "total": total,
                        "completed": completed,
                        "api_calls": batch_total,
                        "current": f"正在合成第 {batch_index}/{batch_total} 批网格图...",
                    },
                }

                image_result = await ai.image_generate(
                    prompt=composed_prompt,
                    model=resolved_engine,
                    size=composite_size,
                    quality=image_quality or ai_config.image.default_quality,
                    negative_prompt=negative_prompt,
                    extra_params=extra_params,
                )
                first = image_result.images[0] if image_result.images else None
                composite_url = first.url if first else None
                if not composite_url:
                    raise ValueError("batch_grid composite API returned no URL")

                logger.info(
                    "batch_grid composite ok, task_id={}, batch={}/{}, splitting url={!r:.50}",
                    task_id,
                    batch_index,
                    batch_total,
                    composite_url,
                )
                cells: list[GridCell] = await image_processor.split_grid(
                    url=composite_url,
                    rows=final_rows,
                    cols=final_cols,
                    gap_px=final_gap,
                    sub_dir="xhs",
                    task_id=task_id,
                    filename_prefix=f"b{batch_index}_",
                    blank_threshold=cfg.blank_threshold,
                    target_cell_size=effective_split_target_cell_size,
                )

                for page, cell in zip(batch_pages, cells, strict=False):
                    page_type = normalize_page_type(page.page_type)
                    if cell.is_blank:
                        failed += 1
                        yield {
                            "event": "page_error",
                            "data": {
                                "index": page.index,
                                "status": "failed",
                                "error": (
                                    f"AI 未在网格 (row {cell.row + 1}, col {cell.col + 1}) "
                                    f"绘制有效内容 (空白占比 {cell.blank_ratio:.0%})"
                                ),
                                "page_type": page_type,
                                "task_id": task_id,
                            },
                        }
                        continue
                    completed += 1
                    yield {
                        "event": "page_done",
                        "data": {
                            "index": page.index,
                            "page_type": page_type,
                            "task_id": task_id,
                            "status": "success",
                            "url": cell.original_url,
                            "image_url": cell.original_url,
                            "original_url": cell.original_url,
                            "thumbnail_url": cell.thumbnail_url,
                            "width": cell.width,
                            "height": cell.height,
                            "original_size": cell.original_size,
                            "thumbnail_size": cell.thumbnail_size,
                            "grid_row": cell.row,
                            "grid_col": cell.col,
                            "batch_index": batch_index,
                            "batch_total": batch_total,
                        },
                    }
                    yield {
                        "event": "progress",
                        "data": {
                            "task_id": task_id,
                            "total": total,
                            "completed": completed,
                            "api_calls": batch_total,
                            "current": f"已完成 {completed}/{total}",
                        },
                    }
            except Exception as exc:
                logger.exception(
                    "batch_grid generation failed: task_id={}, batch={}/{}: {}",
                    task_id,
                    batch_index,
                    batch_total,
                    exc,
                )
                failed += len(batch_pages)
                for page in batch_pages:
                    yield {
                        "event": "page_error",
                        "data": {
                            "index": page.index,
                            "status": "failed",
                            "error": str(exc),
                            "page_type": normalize_page_type(page.page_type),
                            "task_id": task_id,
                        },
                    }

        yield {
            "event": "done",
            "data": {
                "task_id": task_id,
                "total": total,
                "success": completed,
                "failed": failed,
                "mode": "batch_grid",
                "api_calls": batch_total,
                "message": ("全部完成" if failed == 0 else f"{completed} 成功 {failed} 失败"),
            },
        }

    async def _generate_batch_grid_batches_concurrent(
        self,
        *,
        task_id: str,
        page_batches: list[list[XHSPage]],
        total: int,
        final_rows: int,
        final_cols: int,
        final_gap: int,
        split_target_cell_size: Optional[str],
        composite_size: str,
        resolved_engine: str,
        image_quality: Optional[str],
        negative_prompt: Optional[str],
        extra_params: Optional[dict],
        outline: str,
        user_topic: str,
        style_prompt: Optional[str],
        negative_style_prompt: Optional[str],
        user_id: Optional[int],
        blank_threshold: float,
    ) -> AsyncIterator[dict]:
        batch_total = len(page_batches)
        completed = 0
        failed = 0
        max_concurrent_batches = min(2, batch_total)
        batch_semaphore = asyncio.Semaphore(max_concurrent_batches)
        result_queue: asyncio.Queue[dict] = asyncio.Queue()

        logger.info(
            "batch_grid concurrent mode: task_id={}, batches={}, max_concurrent_api_calls={}",
            task_id,
            batch_total,
            max_concurrent_batches,
        )

        async def process_batch(batch_index: int, batch_pages: list[XHSPage]) -> None:
            async with batch_semaphore:
                try:
                    composed_prompt = await self._build_batch_grid_prompt(
                        pages=batch_pages,
                        outline=outline,
                        user_topic=user_topic,
                        rows=final_rows,
                        cols=final_cols,
                        gap_px=final_gap,
                        style_prompt=style_prompt,
                        negative_style_prompt=negative_style_prompt,
                        user_id=user_id,
                    )

                    logger.info(
                        "batch_grid API call start: task_id={}, batch={}/{}, pages={}, size={}, model={}",
                        task_id,
                        batch_index,
                        batch_total,
                        [page.index for page in batch_pages],
                        composite_size,
                        resolved_engine,
                    )
                    await result_queue.put(
                        {
                            "event": "progress",
                            "data": {
                                "task_id": task_id,
                                "total": total,
                                "completed": completed,
                                "api_calls": batch_total,
                                "current": f"rendering batch {batch_index}/{batch_total}...",
                            },
                        }
                    )

                    image_result = await ai.image_generate(
                        prompt=composed_prompt,
                        model=resolved_engine,
                        size=composite_size,
                        quality=image_quality or ai_config.image.default_quality,
                        negative_prompt=negative_prompt,
                        extra_params=extra_params,
                    )
                    first = image_result.images[0] if image_result.images else None
                    composite_url = first.url if first else None
                    if not composite_url:
                        raise ValueError("batch_grid composite API returned no URL")

                    logger.info(
                        "batch_grid composite ok, task_id={}, batch={}/{}, splitting url={!r:.50}",
                        task_id,
                        batch_index,
                        batch_total,
                        composite_url,
                    )
                    cells: list[GridCell] = await image_processor.split_grid(
                        url=composite_url,
                        rows=final_rows,
                        cols=final_cols,
                        gap_px=final_gap,
                        sub_dir="xhs",
                        task_id=task_id,
                        filename_prefix=f"b{batch_index}_",
                        blank_threshold=blank_threshold,
                        target_cell_size=split_target_cell_size,
                    )

                    for page, cell in zip(batch_pages, cells, strict=False):
                        page_type = normalize_page_type(page.page_type)
                        if cell.is_blank:
                            await result_queue.put(
                                {
                                    "event": "page_error",
                                    "data": {
                                        "index": page.index,
                                        "status": "failed",
                                        "error": (
                                            f"AI did not draw valid content in grid "
                                            f"(row {cell.row + 1}, col {cell.col + 1}); "
                                            f"blank ratio {cell.blank_ratio:.0%}"
                                        ),
                                        "page_type": page_type,
                                        "task_id": task_id,
                                    },
                                }
                            )
                            continue

                        await result_queue.put(
                            {
                                "event": "page_done",
                                "data": {
                                    "index": page.index,
                                    "page_type": page_type,
                                    "task_id": task_id,
                                    "status": "success",
                                    "url": cell.original_url,
                                    "image_url": cell.original_url,
                                    "original_url": cell.original_url,
                                    "thumbnail_url": cell.thumbnail_url,
                                    "width": cell.width,
                                    "height": cell.height,
                                    "original_size": cell.original_size,
                                    "thumbnail_size": cell.thumbnail_size,
                                    "grid_row": cell.row,
                                    "grid_col": cell.col,
                                    "batch_index": batch_index,
                                    "batch_total": batch_total,
                                },
                            }
                        )
                except Exception as exc:
                    logger.exception(
                        "batch_grid generation failed: task_id={}, batch={}/{}: {}",
                        task_id,
                        batch_index,
                        batch_total,
                        exc,
                    )
                    for page in batch_pages:
                        await result_queue.put(
                            {
                                "event": "page_error",
                                "data": {
                                    "index": page.index,
                                    "status": "failed",
                                    "error": str(exc),
                                    "page_type": normalize_page_type(page.page_type),
                                    "task_id": task_id,
                                },
                            }
                        )
                finally:
                    await result_queue.put({"event": "_batch_done"})

        batch_tasks = [
            asyncio.create_task(process_batch(batch_index, batch_pages))
            for batch_index, batch_pages in enumerate(page_batches, start=1)
        ]
        remaining_batches = batch_total

        try:
            while remaining_batches > 0:
                event = await result_queue.get()
                event_type = event["event"]

                if event_type == "_batch_done":
                    remaining_batches -= 1
                    continue

                if event_type == "page_done":
                    completed += 1
                elif event_type == "page_error":
                    failed += 1

                yield event

                if event_type in {"page_done", "page_error"}:
                    yield {
                        "event": "progress",
                        "data": {
                            "task_id": task_id,
                            "total": total,
                            "completed": completed,
                            "api_calls": batch_total,
                            "current": f"processed {completed + failed}/{total}",
                        },
                    }
        finally:
            for task in batch_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*batch_tasks, return_exceptions=True)

        yield {
            "event": "done",
            "data": {
                "task_id": task_id,
                "total": total,
                "success": completed,
                "failed": failed,
                "mode": "batch_grid",
                "api_calls": batch_total,
                "message": (
                    "all completed"
                    if failed == 0
                    else f"{completed} succeeded, {failed} failed"
                ),
            },
        }

    # ImageRequest schema hard cap is 4000 chars; leave a small safety margin.
    _BATCH_GRID_PROMPT_MAX_LEN = 3900
    # Per-cell content cap so cells_json doesn't eat the whole budget when the
    # frontend fills each page.image_prompt with a 500-char detailed brief
    # (4 cells × 500 chars ≈ 2000 chars just for JSON, already half the budget).
    _BATCH_GRID_CELL_CONTENT_MAX_LEN = 600

    @staticmethod
    def _truncate_preserving_end(text: str, limit: int) -> str:
        """Truncate text to ``limit`` chars, appending ellipsis if we cut."""
        if len(text) <= limit:
            return text
        ellipsis = "…"
        return text[: max(limit - len(ellipsis), 0)] + ellipsis

    async def _build_batch_grid_prompt(
        self,
        *,
        pages: List[XHSPage],
        outline: str,
        user_topic: str,
        rows: int,
        cols: int,
        gap_px: int,
        style_prompt: Optional[str],
        negative_style_prompt: Optional[str],
        user_id: Optional[int],
    ) -> str:
        """Build the composed poster prompt via ``xhs/batch_grid_prompt`` template.

        The final prompt is sent to ``ai.image_generate`` which has a 4000-char
        hard cap (see ``ImageRequest.prompt.max_length``). We enforce two
        layered budgets to never blow that cap:

        1. **Per-cell content** is truncated to
           :attr:`_BATCH_GRID_CELL_CONTENT_MAX_LEN` chars. Large per-page
           image_prompts are the most common source of overflow.
        2. **Final composed prompt** is truncated to
           :attr:`_BATCH_GRID_PROMPT_MAX_LEN` chars (below 4000 to leave a
           safety margin for Jinja whitespace and downstream middleware).
        """
        cells_payload = []
        total_cells = rows * cols
        for idx in range(total_cells):
            row, col = divmod(idx, cols)
            page = pages[idx] if idx < len(pages) else None
            raw_content = (page.image_prompt or page.content or "").strip() if page else ""
            per_page_prompt = self._truncate_preserving_end(raw_content, self._BATCH_GRID_CELL_CONTENT_MAX_LEN)
            cells_payload.append(
                {
                    "index": idx + 1,
                    "row": row + 1,
                    "col": col + 1,
                    "page_type": (page_type_to_cn(normalize_page_type(page.page_type)) if page else "unused"),
                    "label": f"Cell {idx + 1}",
                    "content": (
                        per_page_prompt
                        if page
                        else "UNUSED CELL: keep this cell pure white and empty. No text, no icon, no decoration, no page marker."
                    ),
                }
            )

        composed = await prompts.get(
            "xhs/batch_grid_prompt",
            {
                "rows": rows,
                "cols": cols,
                "gap_px": gap_px,
                "style_prompt": (style_prompt or "").strip(),
                "negative_style_prompt": (negative_style_prompt or "").strip(),
                "cells_json": json.dumps(cells_payload, ensure_ascii=False, indent=2),
                "user_topic": user_topic or "",
                "outline": outline or "",
            },
            user_id=user_id,
        )
        if not composed:
            parts = [
                f"Render a strict {rows}x{cols} grid of fully independent "
                f"Xiaohongshu pages, separated by {gap_px}px white gaps.",
                "Do not draw page numbers, pagination counters, serial numbers, or progress dots in any cell.",
            ]
            if style_prompt:
                parts.append(f"Style (mandatory for every cell): {style_prompt}")
            if negative_style_prompt:
                parts.append(f"Forbidden elements: {negative_style_prompt}")
            for cell in cells_payload:
                parts.append(f"- Cell {cell['index']} (row {cell['row']}, col {cell['col']}): {cell['content']}")
            composed = "\n\n".join(parts)

        # Final safety net: hard cap to stay below ImageRequest.prompt max_length.
        if len(composed) > self._BATCH_GRID_PROMPT_MAX_LEN:
            original_len = len(composed)
            composed = self._truncate_preserving_end(composed, self._BATCH_GRID_PROMPT_MAX_LEN)
            logger.warning(
                "batch_grid composed prompt truncated: {} → {} chars "
                "(limit={}); consider shortening per-cell image_prompt to "
                "avoid cutting key anti-bleed rules at tail",
                original_len,
                len(composed),
                self._BATCH_GRID_PROMPT_MAX_LEN,
            )
        return composed

    # ------------------------------------------------------------------
    #                batch_grid 子集重绘 (选 N 张一次性出图)
    # ------------------------------------------------------------------

    # 子集重绘固定使用 2x2 竖版联系表。APIMart 支持 9:16/1:1/1:2
    # 这类常见比例,但不支持两个 9:16 页面竖直堆叠后的 9:32。
    # 2x2 可以让合成图和每个裁切 cell 都接近 9:16；未用 cell 提示为空白。
    _SUBSET_GRID_LAYOUT: dict[int, tuple[int, int]] = {
        2: (2, 2),
        3: (2, 2),
        4: (2, 2),
    }

    @classmethod
    def _pick_subset_grid(cls, count: int) -> tuple[int, int]:
        """根据选中页数挑最合适的 (rows, cols) 布局。

        只支持 2/3/4 张:外部 schema 已用 min_length/max_length 把关,
        这里仅做防御性校验并抛一个清晰错误,方便 API 报错上下文。
        """
        if count not in cls._SUBSET_GRID_LAYOUT:
            raise ValueError(f"batch_grid subset regenerate only supports 2/3/4 pages, got {count}")
        return cls._SUBSET_GRID_LAYOUT[count]

    async def regenerate_batch_grid(
        self,
        *,
        all_pages: List[XHSPage],
        page_indexes: List[int],
        outline: str = "",
        user_topic: str = "",
        image_engine: Optional[str] = None,
        image_quality: Optional[str] = None,
        image_style: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        extra_params: Optional[dict] = None,
        user_id: Optional[int] = None,
        style_prompt: Optional[str] = None,
        negative_style_prompt: Optional[str] = None,
        grid_config: Optional[dict] = None,
    ) -> dict:
        """Regenerate a **subset** of pages via a single batch_grid API call.

        Returns a dict matching :class:`BatchGridRegenerateResponse`:
        ``{task_id, rows, cols, mode, fallback_reason, cells, success, failed}``.

        If the composite API call fails (provider refusal, network error,
        split error, etc.) this method returns failed per-cell results and does
        not silently spend additional per-page image calls. The frontend keeps
        the selected pages in a running state while the single composite task is
        pending, then applies the returned per-cell statuses.
        """
        if not page_indexes:
            raise ValueError("page_indexes must contain at least 2 items")
        if len(page_indexes) != len(set(page_indexes)):
            raise ValueError("page_indexes must not contain duplicates")

        cfg = ai_config.image.batch_grid
        task_id = f"regen_grid_{uuid.uuid4().hex[:10]}"

        index_to_page = {page.index: page for page in all_pages}
        try:
            subset_pages = [index_to_page[i] for i in page_indexes]
        except KeyError as exc:
            raise ValueError(f"page_index {exc.args[0]} not found in task pages") from exc

        override = grid_config or {}
        if override.get("rows") and override.get("cols"):
            final_rows = int(override["rows"])
            final_cols = int(override["cols"])
            if final_rows * final_cols < len(subset_pages):
                raise ValueError(
                    f"grid_config rows*cols={final_rows * final_cols} must be >= len(page_indexes)={len(subset_pages)}"
                )
        else:
            final_rows, final_cols = self._pick_subset_grid(len(subset_pages))

        final_gap = int(override.get("gap_px") or cfg.grid_gap_px)
        final_cell_size = str(override.get("cell_size") or DEFAULT_XHS_GRID_CELL_SIZE)
        requested_split_upscale = _as_optional_bool(override.get("split_upscale_enabled"))
        final_split_upscale_enabled = (
            cfg.split_upscale_enabled
            if requested_split_upscale is None
            else requested_split_upscale
        )
        final_split_target_cell_size = str(
            override.get("split_target_cell_size") or cfg.split_target_cell_size
        )
        effective_split_target_cell_size = (
            final_split_target_cell_size if final_split_upscale_enabled else None
        )
        try:
            cell_w_str, cell_h_str = final_cell_size.lower().split("x")
            cell_w = int(cell_w_str)
            cell_h = int(cell_h_str)
        except Exception:
            cell_w, cell_h = 1024, 1024

        composite_w = cell_w * final_cols + final_gap * max(final_cols - 1, 0)
        composite_h = cell_h * final_rows + final_gap * max(final_rows - 1, 0)
        composite_size = f"{composite_w}x{composite_h}"
        resolved_engine = image_engine or ai_config.image.default_model

        logger.info(
            "batch_grid subset regenerate start: task_id={}, indexes={}, "
            "grid(rows x cols)={}x{}, visual(cols x rows)={}x{}, "
            "composite={}, engine={}",
            task_id,
            page_indexes,
            final_rows,
            final_cols,
            final_cols,
            final_rows,
            composite_size,
            resolved_engine,
        )

        def _failed_batch_grid(reason: str) -> dict:
            logger.warning(
                "batch_grid subset regenerate failed without per_page fallback: {} (task_id={}, indexes={})",
                reason,
                task_id,
                page_indexes,
            )
            return {
                "task_id": task_id,
                "rows": final_rows,
                "cols": final_cols,
                "mode": "batch_grid",
                "fallback_reason": reason,
                "cells": [
                    {
                        "page_index": page.index,
                        "status": "failed",
                        "error": reason,
                    }
                    for page in subset_pages
                ],
                "success": 0,
                "failed": len(subset_pages),
            }

        if not cfg.enabled:
            return _failed_batch_grid("batch_grid disabled in settings.toml")
        if cfg.supported_models and resolved_engine not in cfg.supported_models:
            return _failed_batch_grid(f"model '{resolved_engine}' not in batch_grid.supported_models")
        cell_pixels_total = cell_w * cell_h * final_cols * final_rows
        if cell_pixels_total > cfg.max_pixels:
            return _failed_batch_grid(f"cell_pixels_total={cell_pixels_total} > max_pixels={cfg.max_pixels}")

        composed_prompt = await self._build_batch_grid_prompt(
            pages=subset_pages,
            outline=outline,
            user_topic=user_topic,
            rows=final_rows,
            cols=final_cols,
            gap_px=final_gap,
            style_prompt=style_prompt,
            negative_style_prompt=negative_style_prompt,
            user_id=user_id,
        )

        try:
            image_result = await ai.image_generate(
                prompt=composed_prompt,
                model=resolved_engine,
                size=composite_size,
                quality=image_quality or ai_config.image.default_quality,
                negative_prompt=negative_prompt,
                extra_params=extra_params,
            )
            first = image_result.images[0] if image_result.images else None
            composite_url = first.url if first else None
            if not composite_url:
                raise ValueError("batch_grid composite API returned no URL")

            cells: list[GridCell] = await image_processor.split_grid(
                url=composite_url,
                rows=final_rows,
                cols=final_cols,
                gap_px=final_gap,
                sub_dir="xhs",
                task_id=task_id,
                filename_prefix="regen_",
                blank_threshold=cfg.blank_threshold,
                target_cell_size=effective_split_target_cell_size,
            )
        except Exception as exc:
            return _failed_batch_grid(f"composite api/split failed: {exc}")

        cells_out = []
        success = 0
        failed = 0
        for page, cell in zip(subset_pages, cells, strict=False):
            if cell.is_blank:
                failed += 1
                cells_out.append(
                    {
                        "page_index": page.index,
                        "status": "failed",
                        "error": (
                            f"AI 未在网格 (row {cell.row + 1}, col {cell.col + 1}) "
                            f"绘制有效内容 (空白占比 {cell.blank_ratio:.0%})"
                        ),
                    }
                )
                continue
            success += 1
            cells_out.append(
                {
                    "page_index": page.index,
                    "status": "success",
                    "url": cell.original_url,
                    "image_url": cell.original_url,
                    "original_url": cell.original_url,
                    "thumbnail_url": cell.thumbnail_url,
                    "width": cell.width,
                    "height": cell.height,
                }
            )

        return {
            "task_id": task_id,
            "rows": final_rows,
            "cols": final_cols,
            "mode": "batch_grid",
            "fallback_reason": None,
            "cells": cells_out,
            "success": success,
            "failed": failed,
        }

    async def regenerate_single_page(
        self,
        page: XHSPage,
        outline: str = "",
        user_topic: str = "",
        images: Optional[List[str]] = None,
        image_size: Optional[str] = None,
        image_quality: Optional[str] = None,
        image_style: Optional[str] = None,
        image_engine: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        extra_params: Optional[dict] = None,
        user_id: Optional[int] = None,
        style_prompt: Optional[str] = None,
        negative_style_prompt: Optional[str] = None,
    ) -> dict:
        """Regenerate one page image and persist it locally."""
        prompt_text = await self._build_image_prompt(
            page=page,
            outline=outline,
            user_topic=user_topic,
            user_id=user_id,
            style_prompt=style_prompt,
            negative_style_prompt=negative_style_prompt,
        )

        image_result = await self._generate_page_image(
            prompt=prompt_text,
            images=images,
            image_size=image_size,
            image_quality=image_quality,
            image_style=image_style,
            image_engine=image_engine,
            negative_prompt=negative_prompt,
            extra_params=extra_params,
            images_per_page=1,
        )

        first_image = image_result.images[0] if image_result.images else None
        ai_url = first_image.url if first_image else None
        if not ai_url:
            raise ValueError("AI did not return an image URL")

        page_type = normalize_page_type(page.page_type)
        return await self._process_image(
            ai_url=ai_url,
            page=page,
            task_id=f"regen_{page.index}",
            page_type=page_type,
        )
