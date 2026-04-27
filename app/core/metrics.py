"""Prometheus 监控指标模块

提供应用性能监控、业务指标收集功能。

使用方式：
1. 自动收集：HTTP 请求指标自动收集（通过中间件）
2. 手动记录：使用 metrics 对象记录业务指标

示例：
    from app.core.metrics import metrics

    # 记录业务指标
    metrics.increment("user_registrations")
    metrics.observe("ai_response_time", 1.5, labels={"model": "gpt-4"})
"""
from typing import Optional, Callable, Any
from functools import wraps
import time

from fastapi import FastAPI

from app.core.config import settings
from app.core.logger import logger

# Prometheus 客户端（可选依赖）
try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        Info,
        CollectorRegistry,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed, metrics disabled")


class MetricsManager:
    """Prometheus 指标管理器

    Features:
    - 自动 HTTP 请求指标收集
    - 自定义业务指标
    - 多进程支持
    - 优雅降级（无依赖时不报错）
    """

    def __init__(self):
        self.enabled = settings.METRICS_ENABLED and PROMETHEUS_AVAILABLE
        self._registry: Optional[CollectorRegistry] = None
        self._http_requests_total: Optional[Counter] = None
        self._http_request_duration: Optional[Histogram] = None
        self._http_requests_in_progress: Optional[Gauge] = None
        self._app_info: Optional[Info] = None

        # 自定义指标存储
        self._custom_counters: dict = {}
        self._custom_histograms: dict = {}
        self._custom_gauges: dict = {}

        if self.enabled:
            self._init_metrics()

    def _init_metrics(self) -> None:
        """初始化 Prometheus 指标"""
        self._registry = REGISTRY

        # ==================== HTTP 请求指标 ====================

        # 请求总数
        self._http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "path", "status"]
        )

        # 请求延迟分布
        self._http_request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "path"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
        )

        # 当前处理中的请求数
        self._http_requests_in_progress = Gauge(
            "http_requests_in_progress",
            "HTTP requests currently in progress",
            ["method"]
        )

        # ==================== 应用信息 ====================

        self._app_info = Info(
            "app",
            "Application information"
        )
        self._app_info.info({
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": settings.APP_ENV,
        })

        # ==================== 业务指标（预定义）====================

        # 用户相关
        self._custom_counters["user_registrations"] = Counter(
            "user_registrations_total",
            "Total user registrations"
        )
        self._custom_counters["user_logins"] = Counter(
            "user_logins_total",
            "Total user logins",
            ["status"]  # success / failed
        )

        # AI 服务相关
        self._custom_counters["ai_requests"] = Counter(
            "ai_requests_total",
            "Total AI API requests",
            ["service", "model", "status"]  # service: chat/summary/image
        )
        self._custom_histograms["ai_response_time"] = Histogram(
            "ai_response_duration_seconds",
            "AI response time in seconds",
            ["service", "model"],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
        )
        self._custom_counters["ai_tokens"] = Counter(
            "ai_tokens_total",
            "Total AI tokens consumed",
            ["service", "model", "type"]  # type: input / output
        )

        # 缓存相关
        self._custom_counters["cache_hits"] = Counter(
            "cache_hits_total",
            "Total cache hits"
        )
        self._custom_counters["cache_misses"] = Counter(
            "cache_misses_total",
            "Total cache misses"
        )

        # 任务调度相关
        self._custom_counters["scheduled_tasks"] = Counter(
            "scheduled_tasks_total",
            "Total scheduled task executions",
            ["task_name", "status"]  # status: success / failed
        )
        self._custom_histograms["task_duration"] = Histogram(
            "scheduled_task_duration_seconds",
            "Scheduled task duration in seconds",
            ["task_name"],
            buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0)
        )

        # 数据库相关
        self._custom_gauges["db_pool_size"] = Gauge(
            "db_connection_pool_size",
            "Database connection pool size"
        )
        self._custom_gauges["db_pool_checked_out"] = Gauge(
            "db_connection_pool_checked_out",
            "Database connections currently checked out"
        )

        logger.info("Prometheus metrics initialized")

    # ==================== HTTP 指标记录 ====================

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float
    ) -> None:
        """记录 HTTP 请求指标"""
        if not self.enabled:
            return

        # 规范化路径（去除动态参数）
        normalized_path = self._normalize_path(path)

        self._http_requests_total.labels(
            method=method,
            path=normalized_path,
            status=str(status_code)
        ).inc()

        self._http_request_duration.labels(
            method=method,
            path=normalized_path
        ).observe(duration)

    def request_in_progress(self, method: str, delta: int = 1) -> None:
        """更新处理中的请求数"""
        if not self.enabled:
            return

        if delta > 0:
            self._http_requests_in_progress.labels(method=method).inc()
        else:
            self._http_requests_in_progress.labels(method=method).dec()

    # ==================== 业务指标记录 ====================

    def increment(
        self,
        name: str,
        value: float = 1,
        labels: Optional[dict] = None
    ) -> None:
        """增加计数器

        Args:
            name: 指标名称（user_registrations, ai_requests 等）
            value: 增加的值
            labels: 标签字典
        """
        if not self.enabled:
            return

        counter = self._custom_counters.get(name)
        if counter:
            if labels:
                counter.labels(**labels).inc(value)
            else:
                counter.inc(value)

    def observe(
        self,
        name: str,
        value: float,
        labels: Optional[dict] = None
    ) -> None:
        """记录直方图观测值

        Args:
            name: 指标名称（ai_response_time, task_duration 等）
            value: 观测值
            labels: 标签字典
        """
        if not self.enabled:
            return

        histogram = self._custom_histograms.get(name)
        if histogram:
            if labels:
                histogram.labels(**labels).observe(value)
            else:
                histogram.observe(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[dict] = None
    ) -> None:
        """设置 Gauge 值

        Args:
            name: 指标名称
            value: 当前值
            labels: 标签字典
        """
        if not self.enabled:
            return

        gauge = self._custom_gauges.get(name)
        if gauge:
            if labels:
                gauge.labels(**labels).set(value)
            else:
                gauge.set(value)

    # ==================== 便捷方法 ====================

    def record_ai_request(
        self,
        service: str,
        model: str,
        status: str,
        duration: float,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        """记录 AI 请求指标

        Args:
            service: 服务类型 (chat/summary/image/search)
            model: 模型名称
            status: 状态 (success/failed)
            duration: 响应时间（秒）
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
        """
        self.increment("ai_requests", labels={
            "service": service,
            "model": model,
            "status": status
        })

        if status == "success":
            self.observe("ai_response_time", duration, labels={
                "service": service,
                "model": model
            })

        if input_tokens > 0:
            self.increment("ai_tokens", input_tokens, labels={
                "service": service,
                "model": model,
                "type": "input"
            })

        if output_tokens > 0:
            self.increment("ai_tokens", output_tokens, labels={
                "service": service,
                "model": model,
                "type": "output"
            })

    def record_task_execution(
        self,
        task_name: str,
        status: str,
        duration: float
    ) -> None:
        """记录定时任务执行指标"""
        self.increment("scheduled_tasks", labels={
            "task_name": task_name,
            "status": status
        })

        if status == "success":
            self.observe("task_duration", duration, labels={
                "task_name": task_name
            })

    def record_cache_access(self, hit: bool) -> None:
        """记录缓存访问"""
        if hit:
            self.increment("cache_hits")
        else:
            self.increment("cache_misses")

    # ==================== 辅助方法 ====================

    def _normalize_path(self, path: str) -> str:
        """规范化路径，将动态参数替换为占位符

        例如：/api/v1/users/123 → /api/v1/users/{id}
        """
        parts = path.split("/")
        normalized = []

        for part in parts:
            if part.isdigit():
                normalized.append("{id}")
            elif len(part) == 32 and all(c in "0123456789abcdef" for c in part.lower()):
                # UUID 或 MD5
                normalized.append("{uuid}")
            else:
                normalized.append(part)

        return "/".join(normalized)

    def generate_metrics(self) -> tuple[bytes, str]:
        """生成 Prometheus 格式的指标数据"""
        if not self.enabled:
            return b"# Metrics disabled\n", "text/plain"

        return generate_latest(self._registry), CONTENT_TYPE_LATEST


class PrometheusMiddleware:
    """Prometheus 指标收集中间件（纯 ASGI 实现）

    替代 BaseHTTPMiddleware，避免其已知的内存泄漏和流式响应问题。
    """

    def __init__(self, app, metrics_manager: MetricsManager):
        self.app = app
        self.metrics = metrics_manager

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self.metrics.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # 跳过 metrics 端点自身
        if path == settings.METRICS_PATH:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")

        # 记录请求开始
        self.metrics.request_in_progress(method, 1)
        start_time = time.perf_counter()
        status_code = 500  # 默认值（异常时使用）

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            raise
        finally:
            duration = time.perf_counter() - start_time
            self.metrics.request_in_progress(method, -1)
            self.metrics.record_request(
                method=method,
                path=path,
                status_code=status_code,
                duration=duration,
            )


def track_time(metric_name: str, labels: Optional[dict] = None):
    """装饰器：记录函数执行时间到直方图

    示例：
        @track_time("ai_response_time", labels={"service": "chat"})
        async def chat_completion():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start
                metrics.observe(metric_name, duration, labels)

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start
                metrics.observe(metric_name, duration, labels)

        if asyncio_iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def asyncio_iscoroutinefunction(func):
    """检查是否为异步函数"""
    import asyncio
    return asyncio.iscoroutinefunction(func)


# 全局实例
metrics = MetricsManager()


def setup_metrics(app: FastAPI) -> None:
    """设置 Prometheus 监控

    在 FastAPI 应用中启用 Prometheus 监控。

    Args:
        app: FastAPI 应用实例
    """
    if not metrics.enabled:
        logger.info("Prometheus metrics disabled")
        return

    # 添加中间件
    app.add_middleware(PrometheusMiddleware, metrics_manager=metrics)

    # /metrics 端点(带 IP 白名单 + 可选 Bearer token 控制)
    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse as _JSONResponse
    from starlette.responses import Response as _StarletteResponse
    from app.core.utils import get_client_ip

    def _ip_allowed(client_ip: str) -> bool:
        allowed = settings.METRICS_ALLOWED_IPS or []
        if not allowed:
            return True  # 空列表视为关闭白名单
        try:
            import ipaddress

            ip_obj = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        for entry in allowed:
            try:
                if "/" in entry:
                    if ip_obj in ipaddress.ip_network(entry, strict=False):
                        return True
                elif ip_obj == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue
        return False

    @app.get(settings.METRICS_PATH, include_in_schema=False)
    async def prometheus_metrics(request: _Request):
        """Prometheus 指标端点(受 IP 白名单 + 可选 token 保护)"""
        client_ip = get_client_ip(request)
        if not _ip_allowed(client_ip):
            logger.warning("Metrics 访问被拒绝 ip={}", client_ip)
            return _JSONResponse(
                status_code=403, content={"code": 403, "message": "forbidden"}
            )
        if settings.METRICS_AUTH_TOKEN:
            auth = request.headers.get("authorization", "")
            expected = f"Bearer {settings.METRICS_AUTH_TOKEN}"
            if auth != expected:
                return _JSONResponse(
                    status_code=401,
                    content={"code": 401, "message": "unauthorized"},
                )
        content, content_type = metrics.generate_metrics()
        return _StarletteResponse(content=content, media_type=content_type)

    logger.info("Prometheus metrics enabled at {}", settings.METRICS_PATH)
