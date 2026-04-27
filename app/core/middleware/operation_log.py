"""操作日志中间件

记录用户的操作行为，包括请求方法/路径/用户 ID/请求响应摘要/操作耗时。
仅记录写操作（POST/PUT/DELETE）和敏感读操作。

⚠️ 使用纯 ASGI 接口实现，避免 BaseHTTPMiddleware 的请求体读取问题。
"""
import time

from app.core.context import get_request_id
from app.core.logger import logger


class OperationLogMiddleware:
    """操作日志中间件（纯 ASGI 实现）"""

    # 需要记录的路径前缀
    LOG_PATH_PREFIXES = ("/api/",)  # 元组比列表更快

    # 不记录的路径 — frozenset O(1) 查找
    EXCLUDE_PATHS = frozenset({
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
        # SSE 流式端点
        "/api/v1/ai/chat/stream",
        "/api/v1/ai/search/stream",
        "/api/v1/xhs/image/stream",
        "/api/v1/xhs/generate/batch-from-search/stream",
    })

    # 需要记录的方法 — frozenset O(1) 查找
    LOG_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})

    # 最大审计请求体大小：1 MB
    MAX_AUDIT_SIZE = 1 * 1024 * 1024

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        """ASGI 接口入口"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        if not self._should_log(method, path):
            await self.app(scope, receive, send)
            return

        request_id = get_request_id() or "no-id"
        start_time = time.monotonic()

        headers = dict(scope.get("headers", []))
        content_length_bytes = headers.get(b"content-length", b"0")
        try:
            content_length = int(content_length_bytes.decode())
        except (ValueError, AttributeError):
            content_length = 0

        if content_length > self.MAX_AUDIT_SIZE:
            request_summary = "<skipped: too large>"
            # 直接转发，不读取请求体
            await self._forward_and_log(
                scope, receive, send,
                request_id, method, path, start_time, request_summary
            )
            return

        body_received = False
        cached_body = b""

        async def cached_receive():
            """返回缓存的请求体"""
            nonlocal body_received, cached_body
            if not body_received:
                while True:
                    message = await receive()
                    if message["type"] == "http.request":
                        body = message.get("body", b"")
                        cached_body += body
                        if not message.get("more_body", False):
                            break
                    elif message["type"] == "http.disconnect":
                        break
                body_received = True
                return {"type": "http.request", "body": cached_body, "more_body": False}
            # 后续调用，返回空的 disconnect
            return {"type": "http.disconnect"}

        await cached_receive()
        request_summary = self._get_request_summary_from_bytes(cached_body)

        # 创建一个可重复读取的 receive
        body_sent = False

        async def replayable_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": cached_body, "more_body": False}
            return {"type": "http.disconnect"}

        await self._forward_and_log(
            scope, replayable_receive, send,
            request_id, method, path, start_time, request_summary
        )

    async def _forward_and_log(
        self, scope, receive, send,
        request_id: str, method: str, path: str,
        start_time: float, request_summary: str,
    ):
        """转发请求并记录日志"""
        response_status = 500  # 默认状态码

        async def send_wrapper(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.monotonic() - start_time) * 1000

            logger.info(
                "[OP] {} {} | status={} | time={:.1f}ms | body={}",
                method,
                path,
                response_status,
                round(duration_ms, 1),
                request_summary,
            )

    def _should_log(self, method: str, path: str) -> bool:
        """判断是否需要记录（frozenset O(1) 查找）"""
        # 1. 快速方法检查（最先过滤大量 GET 请求）
        if method not in self.LOG_METHODS:
            return False

        # 2. 排除路径（frozenset O(1)）
        if path in self.EXCLUDE_PATHS:
            return False

        # 3. 检查路径前缀（元组可直接传给 startswith）
        return path.startswith(self.LOG_PATH_PREFIXES)

    def _get_request_summary_from_bytes(self, body_bytes: bytes, max_length: int = 500) -> str:
        """从字节获取请求体摘要（安全截断）

        二进制文件（如图片上传）会 decode 失败，返回占位符。
        """
        if not body_bytes:
            return "<empty>"

        try:
            body_str = body_bytes.decode("utf-8", errors="strict")
            if len(body_str) > max_length:
                return body_str[:max_length] + "...(truncated)"
            return body_str
        except UnicodeDecodeError:
            return "<binary data>"
        except Exception:
            return "<unreadable>"
