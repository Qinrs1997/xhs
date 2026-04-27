"""请求追踪中间件

为每个请求生成唯一 ID，并将其注入到日志和响应头中。
支持从请求头读取上游传递的请求 ID（用于分布式追踪）。

使用方法：
    from app.core.middleware import RequestTracingMiddleware
    app.add_middleware(RequestTracingMiddleware)

注意：本模块使用纯 ASGI 接口实现，而非 starlette.middleware.base.BaseHTTPMiddleware，
以避免与 SSE 流式响应不兼容的问题。
"""
import time

from app.core.config import settings
from app.core.context import clear_all_context, set_request_id
from app.core.logger import logger

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_HEADER_LOWER = REQUEST_ID_HEADER.lower().encode()
_REQUEST_ID_HEADER_BYTES = REQUEST_ID_HEADER.encode()


class RequestTracingMiddleware:
    """请求追踪中间件（纯 ASGI 实现）

    功能：
    1. 为每个请求生成/传递请求 ID
    2. 将请求 ID 添加到响应头
    3. 记录请求耗时
    4. 增强日志输出，包含请求 ID

    ⚠️ 使用纯 ASGI 接口实现，避免 starlette BaseHTTPMiddleware 与 SSE 流式响应不兼容的问题。
    """

    def __init__(self, app):
        self.app = app
        # 静默路由：这些路径的访问日志降级为 DEBUG（避免轮询日志刷屏）
        self._quiet_routes = frozenset(
            getattr(settings, "QUIET_ROUTES", []) or []
        )

    async def __call__(self, scope, receive, send):
        """ASGI 接口入口"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        raw_headers = scope.get("headers", [])

        # 从请求头获取请求 ID（分布式追踪场景），否则生成新的
        # 直接遍历元组列表，避免 dict() 转换开销
        incoming_request_id = None
        for hname, hval in raw_headers:
            if hname == _REQUEST_ID_HEADER_LOWER:
                incoming_request_id = hval.decode() or None
                break
        request_id = set_request_id(incoming_request_id)

        headers_dict = dict(raw_headers)  # 仅在需要时转换
        client_ip = self._get_client_ip_from_scope(scope, headers_dict)

        # monotonic 不受系统时间调整影响，更精确
        start_time = time.monotonic()

        is_quiet = path in self._quiet_routes
        req_log_level = "DEBUG" if is_quiet else "INFO"

        logger.log(
            req_log_level,
            "REQ >> {} {} | client={}",
            method,
            path,
            client_ip,
        )

        response_status = 0
        response_started = False

        async def send_wrapper(message):
            nonlocal response_status, response_started

            if message["type"] == "http.response.start":
                response_started = True
                response_status = message.get("status", 200)

                headers_list = list(message.get("headers", []))
                headers_list.append((_REQUEST_ID_HEADER_BYTES, request_id.encode()))

                new_message = dict(message)
                new_message["headers"] = headers_list
                await send(new_message)
            elif message["type"] == "http.response.body":
                # 如果是最后一个 body chunk，记录完成日志
                if not message.get("more_body", False):
                    duration_ms = (time.monotonic() - start_time) * 1000

                    if response_status >= 400:
                        log_level = "WARNING"
                    elif is_quiet:
                        log_level = "DEBUG"
                    else:
                        log_level = "INFO"
                    logger.log(
                        log_level,
                        "RES << {} {} | status={} | time={:.1f}ms",
                        method,
                        path,
                        response_status,
                        duration_ms,
                    )
                await send(message)
            else:
                await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "ERR !! {} {} | error={} | time={:.1f}ms",
                method,
                path,
                str(e),
                duration_ms,
            )
            raise
        finally:
            clear_all_context()

    def _get_client_ip_from_scope(self, scope: dict, headers: dict) -> str:
        """从 ASGI scope 获取客户端 IP（支持代理）"""
        from app.core.utils import get_client_ip_from_scope
        return get_client_ip_from_scope(scope, headers)
