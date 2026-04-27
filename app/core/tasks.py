"""定时任务定义

针对 XHS 创作平台设计的定时任务：
1. 清理临时文件（生图缓存/缩略图/临时上传）
2. AI 用量日报（Token消耗/调用次数/成功率/成本估算）
3. 任务状态巡检（修复卡在 processing 的僵尸任务）
4. 数据库瘦身（清理过期日志/无效会话/孤立数据）
5. 健康巡检（DB/Redis/AI Provider 连通性）
"""
from datetime import timedelta

from app.core.timezone import now_utc

from app.core.scheduler import scheduler, scheduled_task, register_pending_tasks
from app.core.logger import logger
from app.core.config import settings


# ==================== 1. 清理临时文件 ====================

@scheduled_task(
    trigger="cron",
    hour=4,
    minute=0,
    id="cleanup_temp_files",
    name="清理临时文件",
    description="每天凌晨4点清理超过3天的临时图片文件和缩略图",
    is_system=True,
)
def _cleanup_temp_files_sync(upload_dir: str, cutoff_ts: float) -> tuple[int, int]:
    """同步版清理逻辑,供 asyncio.to_thread 调用,避免在事件循环里跑阻塞 I/O"""
    import os
    import glob

    cleaned_count = 0
    cleaned_size = 0
    cleanup_dirs = [
        os.path.join(upload_dir, "temp"),
        os.path.join(upload_dir, "thumbnails"),
    ]
    for dir_path in cleanup_dirs:
        if not os.path.exists(dir_path):
            continue
        try:
            for filepath in glob.glob(
                os.path.join(dir_path, "**", "*"), recursive=True
            ):
                if (
                    os.path.isfile(filepath)
                    and os.path.getmtime(filepath) < cutoff_ts
                ):
                    size = os.path.getsize(filepath)
                    os.remove(filepath)
                    cleaned_count += 1
                    cleaned_size += size
        except Exception as e:
            logger.warning("清理目录 {} 失败: {}", dir_path, e)
    return cleaned_count, cleaned_size


async def cleanup_temp_files():
    """清理生成图片的临时文件(缩略图缓存/下载的原图/临时上传)

    遍历目录与 os.remove 均为阻塞 I/O,放到线程池执行,避免阻塞调度器事件循环。
    """
    import asyncio

    logger.info("开始清理临时文件...")
    cutoff = now_utc().timestamp() - 3 * 86400  # 3天前

    cleaned_count, cleaned_size = await asyncio.to_thread(
        _cleanup_temp_files_sync, settings.UPLOAD_DIR, cutoff
    )

    size_mb = round(cleaned_size / 1024 / 1024, 2)
    logger.info("临时文件清理完成: 删除 {} 个文件, 释放 {} MB", cleaned_count, size_mb)
    return {"cleaned_files": cleaned_count, "freed_mb": size_mb}


# ==================== 2. AI 用量日报 ====================

@scheduled_task(
    trigger="cron",
    hour=0,
    minute=10,
    id="ai_usage_daily_report",
    name="AI用量日报",
    description="每天0:10统计前一天的AI调用量、Token消耗、成功率",
    is_system=True,
)
async def ai_usage_daily_report():
    """生成 AI 用量日报（含 Token 消耗、调用次数、成功率、模型分布）"""
    logger.info("开始生成 AI 用量日报...")

    try:
        from app.core.database import get_async_db_context
        from sqlalchemy import select, func, cast, Integer
        from app.models.ai import AIUsageLog
        from app.models.xhs_task import XHSTask

        yesterday = now_utc().date() - timedelta(days=1)

        async with get_async_db_context() as db:
            # AI 调用统计
            ai_stats = await db.execute(
                select(
                    func.count(AIUsageLog.id).label("total_calls"),
                    func.sum(AIUsageLog.total_tokens).label("total_tokens"),
                    func.sum(AIUsageLog.prompt_tokens).label("prompt_tokens"),
                    func.sum(AIUsageLog.completion_tokens).label("completion_tokens"),
                    func.avg(AIUsageLog.latency_ms).label("avg_latency"),
                    func.sum(cast(AIUsageLog.success, Integer)).label("success_count"),
                ).where(func.date(AIUsageLog.created_at) == yesterday)
            )
            row = ai_stats.one()

            total_calls = row.total_calls or 0
            total_tokens = row.total_tokens or 0
            success = row.success_count or 0
            success_rate = round(success / total_calls * 100, 1) if total_calls > 0 else 100.0
            avg_latency = round(row.avg_latency or 0)

            # 按模型分组统计
            model_stats = await db.execute(
                select(
                    AIUsageLog.model,
                    func.count(AIUsageLog.id).label("calls"),
                    func.sum(AIUsageLog.total_tokens).label("tokens"),
                ).where(func.date(AIUsageLog.created_at) == yesterday)
                .group_by(AIUsageLog.model)
                .order_by(func.sum(AIUsageLog.total_tokens).desc())
            )
            models = [
                {"model": r.model, "calls": r.calls, "tokens": r.tokens or 0}
                for r in model_stats.all()
            ]

            # XHS 任务统计
            task_count = await db.scalar(
                select(func.count(XHSTask.id)).where(
                    func.date(XHSTask.created_at) == yesterday
                )
            ) or 0

            completed_tasks = await db.scalar(
                select(func.count(XHSTask.id)).where(
                    func.date(XHSTask.created_at) == yesterday,
                    XHSTask.status == "completed",
                )
            ) or 0

        report = {
            "date": str(yesterday),
            "ai_calls": total_calls,
            "total_tokens": total_tokens,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "top_models": models[:5],
            "xhs_tasks_created": task_count,
            "xhs_tasks_completed": completed_tasks,
        }

        logger.info(
            "AI用量日报 [{}] — "
            "调用 {} 次, Token {}, "
            "成功率 {}%, 延迟 {}ms, "
            "XHS任务 {}(完成{})",
            yesterday, total_calls, total_tokens,
            success_rate, avg_latency,
            task_count, completed_tasks
        )
        return report

    except Exception as e:
        logger.error("AI 用量日报生成失败: {}", e)
        raise


# ==================== 3. 僵尸任务巡检 ====================

@scheduled_task(
    trigger="interval",
    hours=1,
    id="fix_zombie_tasks",
    name="僵尸任务巡检",
    description="每小时检查卡在 processing 超过30分钟的任务并标记为失败",
    is_system=True,
)
async def fix_zombie_tasks():
    """修复卡在 processing 状态超过30分钟的僵尸任务"""
    try:
        from app.core.database import get_async_db_context
        from sqlalchemy import select, update
        from app.models.xhs_task import XHSTask, TaskStatus

        cutoff = now_utc().replace(tzinfo=None) - timedelta(minutes=30)

        async with get_async_db_context() as db:
            # 查找超时的 generating 任务
            result = await db.execute(
                select(XHSTask.id, XHSTask.title).where(
                    XHSTask.status == TaskStatus.GENERATING,
                    XHSTask.updated_at < cutoff,
                )
            )
            zombie_tasks = result.all()

            if zombie_tasks:
                task_ids = [t.id for t in zombie_tasks]
                await db.execute(
                    update(XHSTask)
                    .where(XHSTask.id.in_(task_ids))
                    .values(
                        status=TaskStatus.FAILED,
                        error_message="任务超时（自动标记为失败，超过30分钟无响应）",
                    )
                )
                await db.commit()

                for t in zombie_tasks:
                    logger.warning("僵尸任务已标记失败: id={}, title={}", t.id, t.title)

                logger.info("僵尸任务巡检完成: 修复 {} 个任务", len(zombie_tasks))
                return {"fixed": len(zombie_tasks), "task_ids": task_ids}
            else:
                logger.debug("僵尸任务巡检: 无异常任务")
                return {"fixed": 0}

    except Exception as e:
        logger.error("僵尸任务巡检失败: {}", e)
        raise


# ==================== 4. 数据库瘦身 ====================

@scheduled_task(
    trigger="cron",
    hour=3,
    minute=0,
    id="database_cleanup",
    name="数据库瘦身",
    description="每天凌晨3点清理过期审计日志(90天)、过期AI会话(30天)、空草稿任务(7天)",
    is_system=True,
)
async def database_cleanup():
    """数据库瘦身：清理过期数据"""
    logger.info("开始数据库瘦身...")
    stats = {}

    try:
        from app.core.database import get_async_db_context
        from sqlalchemy import delete

        async with get_async_db_context() as db:
            # 1. 清理90天前的审计日志
            try:
                from app.models.audit_log import AuditLog
                cutoff_90 = now_utc().replace(tzinfo=None) - timedelta(days=90)
                result = await db.execute(
                    delete(AuditLog).where(AuditLog.created_at < cutoff_90)
                )
                stats["audit_logs"] = result.rowcount
            except Exception as e:
                logger.warning("清理审计日志失败: {}", e)
                stats["audit_logs"] = -1

            # 2. 清理30天前的已归档AI会话
            try:
                from app.models.ai import AIConversation
                cutoff_30 = now_utc().replace(tzinfo=None) - timedelta(days=30)
                result = await db.execute(
                    delete(AIConversation).where(
                        AIConversation.is_archived.is_(True),
                        AIConversation.updated_at < cutoff_30,
                    )
                )
                stats["archived_conversations"] = result.rowcount
            except Exception as e:
                logger.warning("清理AI会话失败: {}", e)
                stats["archived_conversations"] = -1

            # 3. 清理7天前的空草稿任务（没有任何页面数据的废弃草稿）
            try:
                from app.models.xhs_task import XHSTask
                cutoff_7 = now_utc().replace(tzinfo=None) - timedelta(days=7)
                result = await db.execute(
                    delete(XHSTask).where(
                        XHSTask.status == "draft",
                        XHSTask.updated_at < cutoff_7,
                        # pages 为空或 null 的草稿
                        XHSTask.pages.is_(None) | (XHSTask.pages == "[]"),
                    )
                )
                stats["empty_drafts"] = result.rowcount
            except Exception as e:
                logger.warning("清理空草稿失败: {}", e)
                stats["empty_drafts"] = -1

            await db.commit()

        logger.info(
            "数据库瘦身完成: "
            "审计日志 {} 条, "
            "归档会话 {} 条, "
            "空草稿 {} 条",
            stats.get('audit_logs', 0),
            stats.get('archived_conversations', 0),
            stats.get('empty_drafts', 0)
        )
        return stats

    except Exception as e:
        logger.error("数据库瘦身失败: {}", e)
        raise


# ==================== 5. 健康巡检 ====================

@scheduled_task(
    trigger="interval",
    hours=2,
    id="health_check_task",
    name="健康巡检",
    description="每2小时检查数据库、Redis、AI Provider连通性和磁盘空间",
    is_system=True,
)
async def health_check_task():
    """全面健康巡检：DB + Redis + AI Provider + 磁盘"""
    import os
    import shutil
    from app.core.database import async_engine
    from sqlalchemy import text

    issues = []
    checks = {}

    # 1. 数据库连接
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = "error"
        issues.append(f"数据库连接异常: {e}")

    # 2. Redis 连接
    if settings.REDIS_ENABLED:
        try:
            from app.core.cache import cache
            await cache.set("health_check", "ok", ttl=60)
            await cache.delete("health_check")
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = "error"
            issues.append(f"Redis 连接异常: {e}")
    else:
        checks["redis"] = "skipped"

    # 3. AI Provider 可用性（轻量检查，不实际调用 API）
    try:
        from app.ai.config import ai_config
        if ai_config.chat_enabled:
            checks["ai_chat"] = "enabled"
        else:
            checks["ai_chat"] = "disabled"
            issues.append("AI 聊天功能未启用")

        if ai_config.image_enabled:
            checks["ai_image"] = "enabled"
        else:
            checks["ai_image"] = "disabled"
    except Exception as e:
        checks["ai"] = "error"
        issues.append(f"AI 配置检查异常: {e}")

    # 4. 磁盘空间(上传目录所在分区);os.path.exists + shutil.disk_usage 均为阻塞 I/O,放线程池
    import asyncio

    def _disk_probe(path: str) -> tuple[shutil._ntuple_diskusage, str]:
        target = path if os.path.exists(path) else "."
        return shutil.disk_usage(target), target

    try:
        upload_dir = getattr(settings, 'UPLOAD_DIR', '.')
        disk, _ = await asyncio.to_thread(_disk_probe, upload_dir)
        free_gb = round(disk.free / (1024**3), 2)
        total_gb = round(disk.total / (1024**3), 2)
        usage_pct = round((disk.used / disk.total) * 100, 1)
        checks["disk"] = {"free_gb": free_gb, "total_gb": total_gb, "usage_pct": usage_pct}

        if free_gb < 1:
            issues.append(f"磁盘空间不足! 仅剩 {free_gb} GB")
        elif free_gb < 5:
            issues.append(f"磁盘空间警告: 仅剩 {free_gb} GB")
    except Exception:
        checks["disk"] = "error"

    if issues:
        logger.warning("健康巡检发现 {} 个问题: {}", len(issues), issues)
    else:
        logger.info("健康巡检通过: {}", checks)

    return {"status": "warning" if issues else "ok", "checks": checks, "issues": issues}


# ==================== API 可调用任务 ====================

async def sample_task():
    """示例任务 - 可通过 API 创建"""
    logger.info("执行示例任务...")
    return "sample task completed"


async def send_notification_task(message: str = "Hello"):
    """发送通知任务"""
    logger.info("发送通知: {}", message)
    return f"notification sent: {message}"


# ==================== 任务注册 ====================

async def register_all_tasks():
    """
    注册所有定时任务

    在应用启动时调用（main.py 的 lifespan 中）
    """
    # 1. 注册装饰器定义的任务
    await register_pending_tasks()

    # 2. 注册 API 可调用的任务函数
    from app.api.v1.endpoints.scheduler import register_task_func
    register_task_func("sample_task", sample_task)
    register_task_func("send_notification", send_notification_task)
    register_task_func("health_check", health_check_task)

    logger.info("定时任务注册完成，共 {} 个任务", len(scheduler.get_jobs()))


async def start_scheduler():
    """启动调度器"""
    if settings.APP_ENV != "test":  # 测试环境不启动调度器
        await register_all_tasks()
        await scheduler.start()


async def stop_scheduler():
    """停止调度器"""
    await scheduler.shutdown(wait=True)
