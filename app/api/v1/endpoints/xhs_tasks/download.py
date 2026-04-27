"""XHS 任务 ZIP 批量下载端点

接口列表:
- GET /tasks/{id}/download   下载任务图片 + 文案 ZIP(支持 Header 和 Query token)
"""
from __future__ import annotations

import asyncio
import secrets
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_user_from_token_or_query
from app.core.cache import cache
from app.core.config import settings
from app.core.database import get_async_db
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    NotFoundError,
)
from app.core.logger import logger
from app.crud.xhs_task import xhs_task
from app.models.user import User

router = APIRouter()

# 下载一次性 token 的缓存 key 前缀与 TTL(30 秒够浏览器跳转下载即失效)
_DOWNLOAD_TOKEN_PREFIX = "download-token:"
_DOWNLOAD_TOKEN_TTL = 30


# ==================== 工具函数 ====================

def _url_to_local_path(url: str) -> Path | None:
    """将本地 URL 转为文件路径(仅处理 uploads 目录下的文件,防路径穿越)"""
    if not url or not url.startswith("/"):
        return None
    local = Path(url.lstrip("/"))
    try:
        upload_root = Path(settings.UPLOAD_DIR).resolve()
        resolved = local.resolve()
        resolved.relative_to(upload_root)
    except (ValueError, OSError):
        return None
    return local if local.exists() else None


def _format_copywriting(copywriting: dict, task_title: str = "") -> str:
    """将文案 JSON 格式化为可读文本"""
    lines: list[str] = []
    if task_title:
        lines.append(f"任务: {task_title}")
        lines.append("=" * 40)
        lines.append("")

    title = copywriting.get("title", "")
    if title:
        lines.append(f"标题: {title}")
        lines.append("")

    emoji_title = copywriting.get("emoji_title", "")
    if emoji_title and emoji_title != title:
        lines.append(f"备用标题: {emoji_title}")
        lines.append("")

    content = copywriting.get("content", "")
    if content:
        lines.append("正文:")
        lines.append(content)
        lines.append("")

    tags = copywriting.get("tags", [])
    if tags:
        tag_str = " ".join(f"#{tag}" for tag in tags)
        lines.append(f"标签: {tag_str}")

    return "\n".join(lines)


# ==================== 端点 ====================

@router.post(
    "/tasks/{task_id}/download-token",
    summary="获取一次性下载 token(推荐)",
    description=(
        "签发一个仅限该任务、30 秒有效、单次使用的短 token,"
        "浏览器直接触发下载时应先用此端点获取 `dl` 参数,避免把长生命周期 JWT 写进 URL/日志。"
    ),
)
async def create_download_token(
    *,
    task_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")
    # 用 secrets 生成不可预测的 token
    token = secrets.token_urlsafe(24)
    await cache.set(
        _DOWNLOAD_TOKEN_PREFIX + token,
        {"user_id": current_user.id, "task_id": task_id},
        ttl=_DOWNLOAD_TOKEN_TTL,
    )
    return {
        "dl": token,
        "expires_in": _DOWNLOAD_TOKEN_TTL,
        "task_id": task_id,
    }


@router.get(
    "/tasks/{task_id}/download",
    summary="批量下载任务图片(ZIP)",
    description=(
        "打包下载任务的所有图片和文案。\n"
        "认证方式(按推荐度排序):\n"
        "1. ?dl=<短 token>:浏览器直接下载场景,token 由 `POST /tasks/{id}/download-token` 签发,30 秒一次性;\n"
        "2. Authorization: Bearer <JWT>:标准 API 调用;\n"
        "3. ?token=<JWT>:旧兼容路径,仅保留向下兼容,**强烈建议迁移到 `dl`**(JWT 写进 URL 会被日志/Referer 泄露)。"
    ),
)
async def download_task(
    *,
    db: AsyncSession = Depends(get_async_db),
    task_id: int,
    dl: str | None = Query(None, description="一次性下载 token(优先使用)"),
    token: str | None = Query(None, description="JWT token(旧兼容,建议迁移到 dl)"),
    authorization: str | None = Header(None),
) -> Any:
    # 1) 优先识别一次性 download token
    if dl:
        entry = await cache.get(_DOWNLOAD_TOKEN_PREFIX + dl)
        if not entry or entry.get("task_id") != task_id:
            raise AuthenticationError("下载 token 无效或已过期,请刷新后重试")
        # 消费后立即删除,实现一次性语义
        await cache.delete(_DOWNLOAD_TOKEN_PREFIX + dl)
        from app.crud import user as user_crud

        current_user = await user_crud.get(db, id=int(entry["user_id"]))
        if current_user is None or not user_crud.is_active(current_user):
            raise AuthenticationError("用户不存在或未激活")
    else:
        current_user = await get_user_from_token_or_query(
            db, token=token, authorization=authorization
        )

    task = await xhs_task.get_user_task(
        db, task_id=task_id, user_id=current_user.id
    )
    if not task:
        raise NotFoundError("任务不存在或无权访问")

    if not task.pages:
        raise BadRequestError("任务没有可下载的图片")

    type_labels = {"cover": "封面", "content": "正文", "summary": "总结"}

    # 临时文件(SpooledTemporaryFile 防止大任务 OOM, 5MB 后溢出到磁盘);
    # 需在 StreamingResponse 读完后由框架关闭, 不能进 with 作用域, 故显式豁免。
    tmp = tempfile.SpooledTemporaryFile(max_size=5 * 1024 * 1024)  # noqa: SIM115

    from app.core.http_client import get_http_client

    client = await get_http_client()

    file_entries: list[tuple[str, bytes | Path]] = []
    for i, page in enumerate(task.pages):
        original_url = page.get("original_url") or page.get("image_url")
        if not original_url:
            continue

        page_type = page.get("page_type") or (
            page.get("extra", {}).get("type", "content")
            if isinstance(page.get("extra"), dict)
            else "content"
        )
        page_type_label = type_labels.get(page_type, f"页{i + 1}")

        local_path = _url_to_local_path(original_url)
        if local_path and local_path.exists():
            ext = local_path.suffix or ".png"
            arcname = f"xhs_{task_id}/{i + 1:02d}_{page_type_label}{ext}"
            file_entries.append((arcname, local_path))
        elif original_url.startswith(("http://", "https://")):
            try:
                resp = await client.get(original_url)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                ext = ".png"
                if "jpeg" in ct or "jpg" in ct:
                    ext = ".jpg"
                elif "webp" in ct:
                    ext = ".webp"
                arcname = f"xhs_{task_id}/{i + 1:02d}_{page_type_label}{ext}"
                file_entries.append((arcname, resp.content))
            except Exception as dl_err:
                logger.warning(
                    "下载远程图片失败(跳过): {}, 错误: {}", original_url, dl_err
                )

    if task.copywriting:
        copywriting_text = _format_copywriting(task.copywriting, task.title)
        file_entries.append(
            (f"xhs_{task_id}/文案.txt", copywriting_text.encode("utf-8"))
        )

    def _build_zip() -> None:
        """在线程池中同步压缩(避免阻塞事件循环)"""
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, data in file_entries:
                if isinstance(data, Path):
                    zf.write(data, arcname)
                else:
                    zf.writestr(arcname, data)

    await asyncio.to_thread(_build_zip)

    tmp.seek(0)
    filename = f"xhs_{task_id}.zip"

    return StreamingResponse(
        tmp,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
