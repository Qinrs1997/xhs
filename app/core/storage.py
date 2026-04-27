import os
import re
import uuid
import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List
from fastapi import UploadFile

from app.core.exceptions import ValidationError
from app.core.logger import logger

# 扩展名 → 允许的 MIME 类型映射（用于魔数校验）
_EXT_MIME_MAP = {
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "gif": {"image/gif"},
    "webp": {"image/webp"},
    "pdf": {"application/pdf"},
    "svg": {"image/svg+xml", "text/xml", "application/xml"},
}

try:
    import aiofiles
    HAS_AIOFILES = True
except ImportError:
    HAS_AIOFILES = False

from app.core.config import settings

# 异步文件写入的缓冲区大小
CHUNK_SIZE = 64 * 1024  # 64KB


class BaseStorage(ABC):
    """存储抽象基类"""

    @abstractmethod
    async def save(self, file: UploadFile, sub_dir: str = "") -> str:
        """保存文件，返回访问路径"""
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """删除文件（异步）"""
        pass

    def validate_file(self, file: UploadFile, allowed_exts: List[str], max_size: int):
        """通用文件校验（扩展名 + 大小 + MIME 魔数）"""
        # 1. 扩展名校验
        ext = os.path.splitext(file.filename or "")[1][1:].lower()
        if ext not in allowed_exts:
            raise ValidationError(
                f"不支持的文件格式。允许: {', '.join(allowed_exts)}"
            )

        # 2. 文件大小校验
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)

        if size > max_size:
            raise ValidationError(
                f"文件过大。最大允许: {max_size / 1024 / 1024:.1f}MB"
            )

        # 3. MIME 魔数校验（防止攻击者改扩展名上传恶意文件）
        header = file.file.read(2048)
        file.file.seek(0)

        if header:
            # 优先用 python-magic（如果安装了）
            detected_mime = None
            try:
                import magic
                detected_mime = magic.from_buffer(header, mime=True)
            except ImportError:
                # 回退到 mimetypes 根据扩展名推断（精度较低但不引入额外依赖）
                detected_mime = mimetypes.guess_type(file.filename or "")[0]

            if detected_mime:
                allowed_mimes = _EXT_MIME_MAP.get(ext)
                if allowed_mimes and detected_mime not in allowed_mimes:
                    logger.warning(
                        "文件 MIME 不匹配: 扩展名={}, 检测类型={}, 文件名={}",
                        ext, detected_mime, file.filename,
                    )
                    raise ValidationError(
                        f"文件内容与扩展名不匹配（检测到 {detected_mime}）"
                    )

    _SAFE_DIR_RE = re.compile(r'[^a-zA-Z0-9_\-/]')

    @classmethod
    def _sanitize_sub_dir(cls, sub_dir: str) -> str:
        """清理 sub_dir，防止路径穿越攻击"""
        sub_dir = sub_dir.replace("..", "").replace("~", "")
        sub_dir = sub_dir.lstrip("/").lstrip("\\")
        sub_dir = cls._SAFE_DIR_RE.sub('', sub_dir)
        return sub_dir


class LocalStorage(BaseStorage):
    """本地磁盘存储实现（异步优化版）"""

    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.base_url = f"/{settings.UPLOAD_DIR.rstrip('/')}"
        if not self.upload_dir.exists():
            self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, file: UploadFile, sub_dir: str = "") -> str:
        # 使用基类校验（扩展名 + 大小 + MIME 魔数）
        allowed = getattr(settings, "UPLOAD_ALLOWED_EXTENSIONS", ["jpg", "jpeg", "png", "gif", "webp"])
        max_size = getattr(settings, "MAX_UPLOAD_SIZE", 5 * 1024 * 1024)
        self.validate_file(file, allowed, max_size)

        # 安全处理 sub_dir（防路径穿越）
        sub_dir = self._sanitize_sub_dir(sub_dir)
        target_dir = self.upload_dir / sub_dir

        # 二次校验：确保目标路径仍在 upload_dir 内
        try:
            target_dir.resolve().relative_to(self.upload_dir.resolve())
        except ValueError:
            raise ValidationError("非法的上传路径") from None

        target_dir.mkdir(parents=True, exist_ok=True)

        ext = os.path.splitext(file.filename or "")[1].lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        save_path = target_dir / filename

        # 使用异步文件写入避免阻塞事件循环
        if HAS_AIOFILES:
            async with aiofiles.open(save_path, "wb") as buffer:
                # 分块读写，优化大文件处理
                while chunk := await file.read(CHUNK_SIZE):
                    await buffer.write(chunk)
        else:
            # 回退到同步方式（兼容未安装 aiofiles 的情况）
            with save_path.open("wb") as buffer:
                # 重置文件指针
                await file.seek(0)
                content = await file.read()
                buffer.write(content)

        return f"{self.base_url}/{sub_dir}/{filename}".replace("//", "/")

    async def delete(self, file_path: str) -> bool:
        """异步删除文件（含路径安全校验）"""
        # 将访问 URL 转回本地路径进行删除
        relative_path = file_path.replace(self.base_url, "").lstrip("/")
        full_path = self.upload_dir / relative_path

        # 安全校验：确保路径在 upload_dir 内
        try:
            full_path.resolve().relative_to(self.upload_dir.resolve())
        except ValueError:
            logger.warning("删除请求路径越界: {}", file_path)
            return False

        try:
            if full_path.is_file():
                if HAS_AIOFILES:
                    import aiofiles.os
                    await aiofiles.os.remove(full_path)
                else:
                    full_path.unlink()
                return True
        except OSError as e:
            logger.warning("删除文件失败: {}, 错误: {}", full_path, e)
        return False

# 预留：S3Storage, OssStorage 可在此或独立文件实现
# class S3Storage(BaseStorage): ...

# 工厂方法或直接导出实例
def get_storage() -> BaseStorage:
    # 这里可以根据 settings.STORAGE_TYPE 动态返回不同实现
    return LocalStorage()

storage = get_storage()
