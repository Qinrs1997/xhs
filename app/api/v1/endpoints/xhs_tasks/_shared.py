"""XHS 任务模块共享工具

包含多个子模块共用的辅助函数、常量和请求模型。
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import anyio
from pydantic import BaseModel, Field
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.xhs.utils import get_page_num
from app.core.logger import logger
from app.core.timezone import now_utc
from app.crud.xhs_task import xhs_task
from app.models.xhs_task import XHSTask

# ==================== 图片字段保护 ====================

# 前端 autosave 可能不含后端写入的图片 URL,需要保留
_IMAGE_FIELDS = ("image_url", "thumbnail_url", "original_url")
_TERMINAL_PAGE_STATUSES = {"success", "failed", "running"}


def _merge_image_fields(existing_pages: list, new_pages: list) -> None:
    """将 DB 中已有的图片 URL 字段合并到前端传来的新 pages 中。

    规则:对于每个 page,如果前端传来的字段为空但 DB 中有值,则保留 DB 的值。
    这防止 autosave 时意外覆盖后端刚写入的图片 URL。
    """
    existing_by_page_num = {
        get_page_num(page, index + 1): page
        for index, page in enumerate(existing_pages)
        if isinstance(page, dict)
    }

    for i, new_page in enumerate(new_pages):
        old_page = existing_by_page_num.get(get_page_num(new_page, i + 1))
        if old_page is None and i < len(existing_pages):
            old_page = existing_pages[i]
        if not isinstance(old_page, dict) or not isinstance(new_page, dict):
            continue
        for field in _IMAGE_FIELDS:
            old_val = old_page.get(field)
            new_val = new_page.get(field)
            if old_val and not new_val:
                new_page[field] = old_val

        old_extra = old_page.get("extra") or {}
        new_extra = new_page.get("extra") or {}
        if not isinstance(old_extra, dict) or not isinstance(new_extra, dict):
            continue

        old_status = old_extra.get("status")
        new_status = new_extra.get("status")
        if old_status in _TERMINAL_PAGE_STATUSES and new_status in (None, "pending"):
            new_extra["status"] = old_status
            if old_extra.get("error") and not new_extra.get("error"):
                new_extra["error"] = old_extra["error"]

        old_candidates = old_extra.get("image_candidates")
        if old_candidates and not new_extra.get("image_candidates"):
            new_extra["image_candidates"] = old_candidates

        if new_extra:
            new_page["extra"] = new_extra


# ==================== 搜索关联提取 ====================

def _extract_search_id(task) -> int | None:
    """从已加载的 search_task_links 中提取最新的 search_history_id。"""
    links = getattr(task, "search_task_links", None)
    if not links:
        return None
    latest = max(links, key=lambda link: link.id)
    return latest.search_history_id


# ==================== 请求模型 ====================

class AutosaveRequest(BaseModel):
    """自动保存请求(轻量)"""
    pages: list[dict] = Field(..., description="页面内容列表")


# ==================== 增强统计 ====================

async def _build_enhanced_stats(db: AsyncSession, user_id: int) -> dict:
    """构建增强版统计数据(共享逻辑,避免重复代码)"""
    stats = await xhs_task.get_user_task_stats(db, user_id=user_id)

    completed = stats.get("completed", 0)
    failed = stats.get("failed", 0)
    total_finished = completed + failed
    stats["success_rate"] = (
        round(completed / total_finished, 2) if total_finished > 0 else 1.0
    )
    stats["total_tasks"] = stats.get("total", 0)

    today = now_utc().date()
    start_date = today - timedelta(days=6)
    trend_stmt = (
        select(
            cast(XHSTask.created_at, Date).label("day"),
            func.count(XHSTask.id).label("count"),
        )
        .where(
            XHSTask.user_id == user_id,
            cast(XHSTask.created_at, Date) >= start_date,
        )
        .group_by(cast(XHSTask.created_at, Date))
    )
    trend_result = await db.execute(trend_stmt)
    day_counts = {str(row.day): row.count for row in trend_result.all()}

    recent_7days = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        recent_7days.append({
            "date": day.isoformat(),
            "count": day_counts.get(day.isoformat(), 0),
        })
    stats["recent_7days"] = recent_7days

    return stats


# ==================== 文件清理 ====================

async def _cleanup_task_files(pages: list, task_id: int) -> None:
    """异步清理任务关联的本地图片文件。

    遍历 pages 中的 original_url 和 thumbnail_url,删除对应的本地文件
    (仅处理本地路径,跳过远程 URL)。清理失败不抛异常,只记录警告日志。
    """
    if not pages:
        return

    cleaned = 0
    for page in pages:
        for url_key in ("original_url", "thumbnail_url"):
            url = page.get(url_key) if isinstance(page, dict) else None
            if not url or not url.startswith("/"):
                continue
            local_path = Path(url.lstrip("/"))
            local_apath = anyio.Path(local_path)
            try:
                if await local_apath.exists():
                    await local_apath.unlink()
                    cleaned += 1
            except Exception as e:
                logger.warning("清理文件失败: {}, 错误: {}", local_path, e)

    if cleaned > 0:
        logger.info("任务 {} 已清理 {} 个本地文件", task_id, cleaned)
