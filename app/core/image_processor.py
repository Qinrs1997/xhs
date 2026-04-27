"""图片处理模块

提供 AI 生成图片的异步下载、本地持久化、缩略图生成等功能。

核心功能：
1. 异步下载远程图片到本地（防止 AI CDN URL 过期）
2. 生成 WebP 缩略图（前端秒加载，体积仅原图 2-5%）
3. 返回本地 URL 供前端使用
4. **batch_grid 模式**：下载一张合成大图，按 rows x cols 网格切成 N 张独立图 +
   空白占比检测，每张独立保存 + 生成缩略图（见 :meth:`split_grid`）

使用方式：
    from app.core.image_processor import image_processor

    result = await image_processor.process(
        url="https://cdn.xxx/ai-image.png",
        sub_dir="xhs",
        task_id="task_abc123"
    )
    # result.thumbnail_url → "/uploads/xhs/thumbnails/xxx.webp"  (~50KB)
    # result.original_url  → "/uploads/xhs/originals/xxx.png"    (~2MB)
"""
import uuid
import asyncio
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from io import BytesIO

import httpx
import aiofiles

from app.core.config import settings
from app.core.logger import logger


@dataclass
class ProcessedImage:
    """处理后的图片结果"""
    original_url: str           # 本地原图 URL
    thumbnail_url: str          # 本地缩略图 URL
    original_size: int          # 原图字节数
    thumbnail_size: int         # 缩略图字节数
    width: int                  # 原图宽度
    height: int                 # 原图高度
    format: str                 # 原图格式


@dataclass
class GridCell:
    """batch_grid 模式下切割后的单个网格图结果"""
    index: int                  # 切格索引 (0-based, 按行优先顺序)
    row: int                    # 所在行 (0-based)
    col: int                    # 所在列 (0-based)
    original_url: str           # 本地原图 URL
    thumbnail_url: str          # 本地缩略图 URL
    width: int
    height: int
    original_size: int
    thumbnail_size: int
    is_blank: bool              # 是否检测为空白格 (AI 没填内容 / 全白)
    blank_ratio: float          # 空白像素占比 (0-1)


# 默认配置
DEFAULT_THUMBNAIL_WIDTH = 720
DEFAULT_THUMBNAIL_QUALITY = 82
DEFAULT_THUMBNAIL_FORMAT = "webp"
DEFAULT_DOWNLOAD_TIMEOUT = 30


class ImageProcessor:
    """图片处理器

    异步下载远程图片 → 保存原图 → 生成缩略图 → 返回本地 URL
    """

    def __init__(self):
        self._upload_dir = Path(settings.UPLOAD_DIR)
        self._base_url = f"/{settings.UPLOAD_DIR.rstrip('/')}"
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_config(self, key: str, default):
        """从 settings / AI 图像配置获取图片处理配置。"""
        value = getattr(settings, key, None)
        if value is not None:
            return value

        # 历史上 settings.toml 的 [ai.image] 缩略图配置只进入 ai_config,
        # 而这里读取 IMAGE_* 字段,导致运行时退回 320/60。这里做一次
        # 懒加载桥接,让 TOML 配置真正控制图片持久化质量。
        try:
            from app.ai.config import ai_config

            ai_image_key_map = {
                "IMAGE_THUMBNAIL_WIDTH": "thumbnail_width",
                "IMAGE_THUMBNAIL_QUALITY": "thumbnail_quality",
                "IMAGE_THUMBNAIL_FORMAT": "thumbnail_format",
                "IMAGE_DOWNLOAD_TIMEOUT": "download_timeout",
            }
            attr = ai_image_key_map.get(key)
            if attr:
                return getattr(ai_config.image, attr, default)
        except Exception:
            pass

        return default

    @staticmethod
    def _parse_size(size: str | None) -> tuple[int, int] | None:
        if not size:
            return None
        try:
            width_text, height_text = size.lower().split("x", 1)
            width = int(width_text)
            height = int(height_text)
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    @property
    def thumbnail_width(self) -> int:
        return self._get_config("IMAGE_THUMBNAIL_WIDTH", DEFAULT_THUMBNAIL_WIDTH)

    @property
    def thumbnail_quality(self) -> int:
        return self._get_config("IMAGE_THUMBNAIL_QUALITY", DEFAULT_THUMBNAIL_QUALITY)

    @property
    def thumbnail_format(self) -> str:
        return self._get_config("IMAGE_THUMBNAIL_FORMAT", DEFAULT_THUMBNAIL_FORMAT)

    @property
    def download_timeout(self) -> int:
        return self._get_config("IMAGE_DOWNLOAD_TIMEOUT", DEFAULT_DOWNLOAD_TIMEOUT)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（复用连接池）"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=self.download_timeout,
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                ),
            )
        return self._http_client

    async def close(self):
        """关闭 HTTP 客户端（应用关闭时调用）"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def process(
        self,
        url: str,
        sub_dir: str = "xhs",
        task_id: Optional[str] = None,
        filename_prefix: Optional[str] = None,
    ) -> ProcessedImage:
        """处理远程图片：下载 → 保存原图 → 生成缩略图

        Args:
            url: 远程图片 URL（AI 生成的临时 CDN 地址）
            sub_dir: 子目录（如 "xhs"）
            task_id: 任务 ID（用于文件命名，便于归类）
            filename_prefix: 文件名前缀

        Returns:
            ProcessedImage 包含本地 URL 和图片信息
        """
        # 1. 下载原图到内存
        image_data = await self._download(url)
        if not image_data:
            raise ValueError(f"图片下载失败: {url}")

        # 2. 生成文件名
        file_id = uuid.uuid4().hex[:12]
        prefix = filename_prefix or (f"{task_id}_" if task_id else "")
        base_name = f"{prefix}{file_id}"

        # 3. 解析图片信息 + 生成缩略图（在线程池中执行，不阻塞事件循环）
        original_info, thumbnail_data = await asyncio.to_thread(
            self._process_image_sync, image_data
        )

        # 4. 确定文件路径
        original_ext = original_info["format"].lower()
        if original_ext == "jpeg":
            original_ext = "jpg"

        originals_dir = self._upload_dir / sub_dir / "originals"
        thumbnails_dir = self._upload_dir / sub_dir / "thumbnails"
        originals_dir.mkdir(parents=True, exist_ok=True)
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        original_path = originals_dir / f"{base_name}.{original_ext}"
        thumbnail_path = thumbnails_dir / f"{base_name}.{self.thumbnail_format}"

        # 5. 异步写入文件
        await asyncio.gather(
            self._save_file(original_path, image_data),
            self._save_file(thumbnail_path, thumbnail_data),
        )

        # 6. 构建 URL
        original_url = f"{self._base_url}/{sub_dir}/originals/{original_path.name}"
        thumbnail_url = f"{self._base_url}/{sub_dir}/thumbnails/{thumbnail_path.name}"

        logger.info(
            "图片处理完成: 原图 {:.0f}KB → 缩略图 {:.0f}KB ({:.0f}% 压缩率)",
            len(image_data) / 1024, len(thumbnail_data) / 1024,
            len(thumbnail_data) / len(image_data) * 100
        )

        return ProcessedImage(
            original_url=original_url,
            thumbnail_url=thumbnail_url,
            original_size=len(image_data),
            thumbnail_size=len(thumbnail_data),
            width=original_info["width"],
            height=original_info["height"],
            format=original_info["format"],
        )

    async def _download(self, url: str) -> Optional[bytes]:
        """异步下载远程图片"""
        try:
            client = await self._get_client()
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                logger.warning("非图片类型: {}, URL: {}", content_type, url)

            data = response.content
            logger.debug("图片下载完成: {:.0f}KB, URL: {}...", len(data) / 1024, url[:80])
            return data

        except httpx.TimeoutException:
            logger.error("图片下载超时: {}", url)
            return None
        except httpx.HTTPStatusError as e:
            logger.error("图片下载 HTTP 错误 {}: {}", e.response.status_code, url)
            return None
        except Exception as e:
            logger.error("图片下载失败: {}, URL: {}", e, url)
            return None

    def _process_image_sync(self, image_data: bytes) -> tuple:
        """同步处理图片（在线程池中执行）

        Returns:
            (original_info, thumbnail_data)
        """
        from PIL import Image

        # 解析原图信息
        img = Image.open(BytesIO(image_data))
        original_info = {
            "width": img.width,
            "height": img.height,
            "format": img.format or "PNG",
        }

        # 生成缩略图
        thumbnail_data = self._generate_thumbnail(img)

        return original_info, thumbnail_data

    def _generate_thumbnail(self, img) -> bytes:
        """生成缩略图

        保持宽高比，缩小到指定宽度，转为 WebP 格式。
        """
        from PIL import Image

        # 计算缩放比例（保持宽高比）
        target_width = self.thumbnail_width
        if img.width <= target_width:
            # 原图已经很小，不需要缩放，只做格式转换和压缩
            target_width = img.width

        ratio = target_width / img.width
        target_height = int(img.height * ratio)

        # 高质量缩放
        thumbnail = img.resize(
            (target_width, target_height),
            Image.Resampling.LANCZOS,
        )

        # 转为 RGB（WebP 不支持 RGBA 的某些模式）
        if thumbnail.mode in ("RGBA", "LA", "P"):
            # 如果有透明通道，用白色背景合成
            background = Image.new("RGB", thumbnail.size, (255, 255, 255))
            if thumbnail.mode == "P":
                thumbnail = thumbnail.convert("RGBA")
            background.paste(thumbnail, mask=thumbnail.split()[-1] if thumbnail.mode == "RGBA" else None)
            thumbnail = background
        elif thumbnail.mode != "RGB":
            thumbnail = thumbnail.convert("RGB")

        # 导出为 WebP/JPEG
        buffer = BytesIO()
        fmt = self.thumbnail_format.upper()
        if fmt == "WEBP":
            thumbnail.save(buffer, format="WEBP", quality=self.thumbnail_quality, method=4)
        elif fmt in ("JPEG", "JPG"):
            thumbnail.save(buffer, format="JPEG", quality=self.thumbnail_quality, optimize=True)
        else:
            thumbnail.save(buffer, format="WEBP", quality=self.thumbnail_quality, method=4)

        return buffer.getvalue()

    async def _save_file(self, path: Path, data: bytes):
        """异步保存文件"""
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)

    # ==================================================================
    #                       batch_grid 切格模式
    # ==================================================================

    async def split_grid(
        self,
        url: str,
        *,
        rows: int,
        cols: int,
        gap_px: int = 0,
        sub_dir: str = "xhs",
        task_id: Optional[str] = None,
        filename_prefix: Optional[str] = None,
        blank_threshold: float = 0.6,
        target_cell_size: Optional[str] = None,
    ) -> list[GridCell]:
        """把一张网格合成图按 rows x cols 切成 rows*cols 张独立图。

        供 XHS "batch_grid" 生图模式使用：AI 一次生成一张 2x2 等网格大图，
        后端下载后按坐标切成若干子图并各自生成缩略图。每格单独做空白占比
        检测：当 ``blank_ratio >= blank_threshold`` 时 ``is_blank=True``，
        上层服务可以据此判定"AI 没画出这一格"，给前端 ``page_error``。

        Args:
            url: 合成大图的远程 URL（AI 返回）
            rows / cols: 网格行列数 (一般 2/2)
            gap_px: 网格间隔像素（切割时会跳过这些分隔带，避免把白线当内容）
            sub_dir: 落盘子目录
            task_id / filename_prefix: 文件命名用
            blank_threshold: 空白占比阈值 (0~1)，默认 0.6
            target_cell_size: 可选的切割后目标尺寸 (如 1024x1792)。当模型返回
                的网格合成图像素较低时,用高质量 Lanczos + 轻锐化放大后保存,
                避免前端把 500px 宽小图直接拉伸导致明显发糊。

        Returns:
            list[GridCell]，按行优先顺序排列（row=0,col=0 → row=0,col=1 → ...）
        """
        if rows < 1 or cols < 1:
            raise ValueError(f"split_grid rows/cols must be >= 1, got rows={rows} cols={cols}")

        # 1. 下载合成图
        image_data = await self._download(url)
        if not image_data:
            raise ValueError(f"合成图下载失败: {url}")

        # 2. 切图 + 缩略 (在线程池,不阻塞事件循环)
        cells_data = await asyncio.to_thread(
            self._split_grid_sync,
            image_data,
            rows=rows,
            cols=cols,
            gap_px=gap_px,
            blank_threshold=blank_threshold,
            target_cell_size=target_cell_size,
        )

        # 3. 准备目录
        originals_dir = self._upload_dir / sub_dir / "originals"
        thumbnails_dir = self._upload_dir / sub_dir / "thumbnails"
        originals_dir.mkdir(parents=True, exist_ok=True)
        thumbnails_dir.mkdir(parents=True, exist_ok=True)

        grid_batch_id = uuid.uuid4().hex[:12]
        prefix = filename_prefix or (f"{task_id}_" if task_id else "")

        # 4. 异步写盘
        results: list[GridCell] = []
        write_tasks: list = []
        for cell in cells_data:
            base_name = f"{prefix}grid_{grid_batch_id}_r{cell['row']}c{cell['col']}"
            original_ext = "png"  # 切图统一以 PNG 保存(无损,方便二次处理)
            original_path = originals_dir / f"{base_name}.{original_ext}"
            thumbnail_path = thumbnails_dir / f"{base_name}.{self.thumbnail_format}"

            write_tasks.append(self._save_file(original_path, cell["original_data"]))
            write_tasks.append(self._save_file(thumbnail_path, cell["thumbnail_data"]))

            original_url = (
                f"{self._base_url}/{sub_dir}/originals/{original_path.name}"
            )
            thumbnail_url = (
                f"{self._base_url}/{sub_dir}/thumbnails/{thumbnail_path.name}"
            )
            results.append(
                GridCell(
                    index=cell["index"],
                    row=cell["row"],
                    col=cell["col"],
                    original_url=original_url,
                    thumbnail_url=thumbnail_url,
                    width=cell["width"],
                    height=cell["height"],
                    original_size=len(cell["original_data"]),
                    thumbnail_size=len(cell["thumbnail_data"]),
                    is_blank=cell["is_blank"],
                    blank_ratio=cell["blank_ratio"],
                )
            )

        await asyncio.gather(*write_tasks)

        non_blank = sum(1 for c in results if not c.is_blank)
        logger.info(
            "split_grid done: url_preview={!r:.50}, rows={}, cols={}, "
            "cells={}, non_blank={}, blank_threshold={}",
            url,
            rows,
            cols,
            len(results),
            non_blank,
            blank_threshold,
        )
        return results

    def _split_grid_sync(
        self,
        image_data: bytes,
        *,
        rows: int,
        cols: int,
        gap_px: int,
        blank_threshold: float,
        target_cell_size: Optional[str] = None,
    ) -> list[dict]:
        """同步切图 (线程池内运行)。"""
        from PIL import Image, ImageFilter

        img = Image.open(BytesIO(image_data))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        img_w, img_h = img.width, img.height
        # 扣掉 (cols-1)*gap 的分隔带,剩下平分
        total_gap_w = gap_px * max(cols - 1, 0)
        total_gap_h = gap_px * max(rows - 1, 0)
        cell_w = (img_w - total_gap_w) // cols
        cell_h = (img_h - total_gap_h) // rows
        if cell_w <= 0 or cell_h <= 0:
            raise ValueError(
                f"split_grid: cell size non-positive (cell_w={cell_w}, cell_h={cell_h}); "
                f"check input image size {img_w}x{img_h} vs rows={rows}/cols={cols}/gap={gap_px}"
            )

        target_size = self._parse_size(target_cell_size)
        cells: list[dict] = []
        for r in range(rows):
            for c in range(cols):
                left = c * (cell_w + gap_px)
                upper = r * (cell_h + gap_px)
                right = left + cell_w
                lower = upper + cell_h
                crop = img.crop((left, upper, right, lower))
                crop_rgb = crop.convert("RGB") if crop.mode != "RGB" else crop
                output_rgb = crop_rgb

                # Blank ratio check on a 64x64 sample. Keep this dependency-free:
                # Pillow is already required by the image pipeline, numpy is not.
                small = crop_rgb.resize((64, 64), Image.Resampling.NEAREST)
                total_pixels = small.width * small.height
                pixels = (
                    small.get_flattened_data()
                    if hasattr(small, "get_flattened_data")
                    else small.getdata()
                )
                near_white_pixels = sum(
                    1
                    for red, green, blue in pixels
                    if red > 245 and green > 245 and blue > 245
                )
                blank_ratio = near_white_pixels / total_pixels
                is_blank = blank_ratio >= blank_threshold

                if target_size:
                    target_w, target_h = target_size
                    should_upscale = crop_rgb.width < target_w or crop_rgb.height < target_h
                    if should_upscale:
                        crop_aspect = crop_rgb.width / crop_rgb.height
                        target_aspect = target_w / target_h
                        if abs(crop_aspect - target_aspect) / target_aspect <= 0.08:
                            next_size = (target_w, target_h)
                        else:
                            scale = max(target_w / crop_rgb.width, target_h / crop_rgb.height)
                            next_size = (
                                max(1, round(crop_rgb.width * scale)),
                                max(1, round(crop_rgb.height * scale)),
                            )
                        output_rgb = crop_rgb.resize(next_size, Image.Resampling.LANCZOS)
                        output_rgb = output_rgb.filter(
                            ImageFilter.UnsharpMask(radius=1.1, percent=120, threshold=3)
                        )

                # 原图数据 (PNG 无损) + 缩略图 (复用已有方法)
                original_buf = BytesIO()
                output_rgb.save(original_buf, format="PNG", optimize=True)
                original_data = original_buf.getvalue()
                thumbnail_data = self._generate_thumbnail(output_rgb)

                cells.append(
                    {
                        "index": r * cols + c,
                        "row": r,
                        "col": c,
                        "width": output_rgb.width,
                        "height": output_rgb.height,
                        "original_data": original_data,
                        "thumbnail_data": thumbnail_data,
                        "blank_ratio": blank_ratio,
                        "is_blank": is_blank,
                    }
                )
        return cells


# 全局图片处理器实例
image_processor = ImageProcessor()
