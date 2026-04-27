"""响应包装中间件

统一 API 响应格式。如果 API 返回的不是标准 Response 结构，
自动将其包装为的标准格式：

    {
        "code": 200,
        "success": true,
        "message": "success",
        "data": payload
    }

仅处理：
- 状态码为 2xx 的成功响应
- Content-Type 为 application/json 的响应
- 非流式响应（根据 more_body 判断，SSE 会跳过）
"""

from ._json import json_dumps, json_loads

_CONTENT_LENGTH = b"content-length"


class ResponseNormalizationMiddleware:
    """响应包装中间件（纯 ASGI 实现）"""

    # 不做包装的路径 — 这些路径返回的 JSON 有自己的格式要求
    SKIP_PATHS = frozenset({
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    })

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 跳过 FastAPI 内部文档端点（OpenAPI schema / Swagger UI / ReDoc）
        path = scope.get("path", "/")
        if path in self.SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # 预先定义变量，主要用于捕获
        start_message = None
        response_headers: list = []
        response_status = 200

        is_json = False
        should_wrap = False

        async def send_wrapper(message):
            nonlocal start_message, response_headers, response_status
            nonlocal is_json, should_wrap

            if message["type"] == "http.response.start":
                start_message = message
                response_status = message.get("status", 200)
                response_headers = message.get("headers", [])

                content_type = b""
                for k, v in response_headers:
                    if k == b"content-type":
                        content_type = v
                        break

                is_json = b"application/json" in content_type
                is_sse = b"text/event-stream" in content_type

                # 只有 200-299 的 JSON 响应才可能需要包装；显式排除 SSE 或其他流式
                should_wrap = is_json and (200 <= response_status < 300) and not is_sse

                if not should_wrap:
                    await send(message)
                # 如果 should_wrap，暂停发送 start，等待 body 检查

            elif message["type"] == "http.response.body":
                if not should_wrap or start_message is None:
                    await send(message)
                    return

                # 如果有 more_body，说明是流式响应（虽然是 JSON），为了安全放弃包装
                if message.get("more_body", False):
                    await send(start_message)
                    start_message = None
                    await send(message)
                    return

                # 这是一个完整的 JSON Body
                body = message.get("body", b"")

                try:
                    if not body:
                        # Body 为空（如 204），不包装
                        await send(start_message)
                        await send(message)
                        return

                    original_data = json_loads(body)

                    # 检查是否已经是标准格式：必须是 dict，且包含 'code' 字段
                    if isinstance(original_data, dict) and "code" in original_data:
                        await send(start_message)
                        await send(message)
                        return

                    wrapper = {
                        "code": response_status,
                        "success": True,
                        "message": "success",
                        "data": original_data,
                    }

                    new_body = json_dumps(wrapper)

                    # 更新 Content-Length 头
                    new_headers = [
                        (k, v) for k, v in response_headers if k != _CONTENT_LENGTH
                    ]
                    new_headers.append((b"content-length", str(len(new_body)).encode()))

                    start_message["headers"] = new_headers
                    await send(start_message)

                    await send({
                        "type": "http.response.body",
                        "body": new_body,
                        "more_body": False,
                    })

                except Exception:
                    # 解析失败（非合法 JSON）或其他错误兜底，原样发送，防止破坏应用
                    await send(start_message)
                    await send(message)

        await self.app(scope, receive, send_wrapper)
