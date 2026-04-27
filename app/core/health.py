"""健康检查模块

提供应用健康状态检测,支持 Liveness / Readiness 拆分。

- `/health/live`      轻量存活(只返回 ok)
- `/health/ready`     深度就绪(DB 必查,REDIS_ENABLED 时附带 Redis ping)
- `/health`           向 K8s/LB 暴露,仅输出总状态与组件 status(不泄露版本/内存/连接池等敏感细节)
- `/health/detail`    管理员专用的详细健康报告(super user JWT 保护)

探针友好:
- `/health/live` / `/health/ready` 响应体简洁,不泄露内部信息
- `/health` 去掉了之前返回的 version / pool 统计 / system 内存等信息
- 需要详细信息请走 `/health/detail`(鉴权后可读)
"""
import time
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.context import get_request_id
from app.core.logger import logger
from app.core.database import async_engine

router = APIRouter(tags=["健康检查"])


@router.get("/health/live")
async def liveness():
    """存活检测(Liveness Probe),仅返回应用进程是否存活,不检查任何依赖。"""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness():
    """就绪检测(Readiness Probe)

    - 必查:数据库连接
    - 可选:`REDIS_ENABLED=True` 时必须 Redis 可达,否则黑名单/限流/幂等缓存都不可用
    """
    failures: list[str] = []
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.warning("就绪检查数据库失败: {}", e)
        failures.append("database")

    if settings.REDIS_ENABLED:
        try:
            from app.core.cache import cache

            # 直接用 set/get 做往返验证(Redis 后端会走真实网络);出错会抛
            probe_key = "_ready_probe"
            await cache.set(probe_key, "1", ttl=5)
            if await cache.get(probe_key) != "1":
                failures.append("redis")
        except Exception as e:
            logger.warning("就绪检查 Redis 失败: {}", e)
            failures.append("redis")

    if failures:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": failures},
        )
    return {"status": "ok"}


@router.get("/health")
async def health_check_summary():
    """轻量聚合健康视图(对外暴露,不泄露敏感细节)

    - 只返回组件的 status 字段 + 整体 status
    - 不返回版本、内存、连接池、AI 提供商名称等内部信息
    """
    db_ok = "ok"
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = "error"

    cache_status = "disabled"
    if settings.REDIS_ENABLED:
        try:
            from app.core.cache import cache

            await cache.set("_health_probe", "ok", ttl=5)
            if await cache.get("_health_probe") == "ok":
                cache_status = "ok"
            else:
                cache_status = "error"
        except Exception:
            cache_status = "error"

    overall = "healthy" if db_ok == "ok" and cache_status != "error" else "unhealthy"
    return {
        "status": overall,
        "components": {"database": db_ok, "cache": cache_status},
    }


def include_detailed_health_if_available(app):
    """按需挂载 /health/detail(由 main.py 在路由注册阶段调用)

    此时 `app.api.deps` 已经可以安全 import。
    """
    from fastapi import APIRouter
    from app.api.deps import get_current_superuser

    detail_router = APIRouter(tags=["健康检查"])

    @detail_router.get("/health/detail", include_in_schema=False)
    async def health_check_detailed(_user=Depends(get_current_superuser)):
        return await _build_detailed_health()

    app.include_router(detail_router)


async def _build_detailed_health() -> dict:
    """构造详细健康报告(/health/detail 使用)"""
    start_time = time.perf_counter()

    result = {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.APP_ENV,
        "dependencies": {},
        "system": {}
    }

    # 1. 检查数据库
    result["dependencies"]["database"] = await _check_database(async_engine)
    if result["dependencies"]["database"].get("status") == "error":
        result["status"] = "unhealthy"

    # 2. 检查 AI 服务
    result["dependencies"]["ai_service"] = await _check_ai_service()

    # 3. 检查缓存
    result["dependencies"]["cache"] = await _check_cache()

    # 4. 检查调度器
    result["dependencies"]["scheduler"] = _check_scheduler()

    # 5. 系统信息（IO 密集的 psutil 放线程池执行，避免阻塞事件循环）
    import asyncio
    result["system"] = await asyncio.to_thread(_get_system_info)

    # 响应时间
    total_latency = (time.perf_counter() - start_time) * 1000
    result["response_time_ms"] = round(total_latency, 2)
    result["request_id"] = get_request_id()

    return result


# ==================== 各依赖检查函数 ====================

async def _check_database(engine) -> dict:
    """检查数据库连接"""
    try:
        db_start = time.perf_counter()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - db_start) * 1000

        # 连接池状态
        pool_status = {}
        pool = engine.pool
        try:
            pool_status = {
                "pool_size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "max_overflow": pool._max_overflow,
            }
        except Exception:
            pool_status = {"info": "pool stats unavailable"}

        return {
            "status": "ok",
            "latency_ms": round(db_latency, 2),
            "pool": pool_status,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def _check_ai_service() -> dict:
    """检查 AI 服务"""
    try:
        from app.ai.facade import ai
        if ai.is_initialized:
            ai_health = await ai.health_check()
            return {
                "status": ai_health.get("status", "ok"),
                "provider": ai_health.get("provider", "unknown")
            }
        else:
            return {"status": "not_initialized"}
    except Exception:
        return {"status": "error"}


async def _check_cache() -> dict:
    """检查缓存服务"""
    try:
        from app.core.cache import cache
        if cache._backend is not None:
            cache_start = time.perf_counter()
            await cache.set("_health_check", "ok", ttl=10)
            result = await cache.get("_health_check")
            cache_latency = (time.perf_counter() - cache_start) * 1000
            return {
                "status": "ok" if result == "ok" else "error",
                "type": cache._backend.__class__.__name__,
                "latency_ms": round(cache_latency, 2)
            }
        else:
            return {"status": "disabled"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _check_scheduler() -> dict:
    """检查调度器"""
    try:
        from app.core.scheduler import scheduler
        if scheduler.is_running:
            stats = scheduler.stats()
            return {
                "status": "running",
                "jobs_count": stats.get("total_jobs", 0),
                "running_jobs": stats.get("running_jobs", 0)
            }
        else:
            return {"status": "stopped"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _get_system_info() -> dict:
    """获取系统信息"""
    try:
        import os
        import psutil

        current_process = psutil.Process(os.getpid())
        parent_process = current_process.parent()

        total_memory = current_process.memory_info().rss
        total_threads = current_process.num_threads()

        # 如果有父进程且是 uvicorn，统计所有子进程
        if parent_process and 'uvicorn' in ' '.join(parent_process.cmdline()):
            for child in parent_process.children(recursive=True):
                try:
                    total_memory += child.memory_info().rss
                    total_threads += child.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        system_cpu = psutil.cpu_percent(interval=None)
        try:
            load_avg = psutil.getloadavg()
            load_average = round(load_avg[0], 2)
        except (AttributeError, OSError):
            load_average = system_cpu
        mem_info = psutil.virtual_memory()

        return {
            "cpu_percent": system_cpu,
            "load_average": load_average,
            "memory_mb": round(total_memory / 1024 / 1024, 2),
            "total_memory_mb": round(mem_info.total / 1024 / 1024, 2),
            "threads": total_threads,
            "uptime_seconds": int(time.time() - current_process.create_time())
        }
    except ImportError:
        return {"note": "psutil not installed"}
    except Exception as e:
        return {"error": str(e)}
