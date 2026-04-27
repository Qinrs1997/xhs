"""安全响应头中间件

为 API 响应统一添加一组业界标准的"防守性"响应头:

- `Strict-Transport-Security`  强制 HTTPS(仅在 HTTPS 请求上附加)
- `X-Content-Type-Options`     阻止 MIME sniffing(防 CSS/JS 被当成其它类型执行)
- `X-Frame-Options`            禁止被嵌入 iframe(防点击劫持)
- `Referrer-Policy`            跨站跳转不泄露完整 URL
- `Permissions-Policy`         关闭若干高风险浏览器 API(默认)
- `X-XSS-Protection`           老浏览器 XSS 过滤(新浏览器已弃用,保留向下兼容)

设计要点:
- 默认对所有响应生效;前端反代若已经加过同名头不会被覆盖(我们用 setdefault 语义)
- HSTS 只在明确走 HTTPS(或反代 `X-Forwarded-Proto=https`)时注入,避免 dev 误用
- 纯 ASGI 实现,和其它中间件一致,保持响应链可组合
"""
from __future__ import annotations

from app.core.config import settings


class SecurityHeadersMiddleware:
    """注入通用安全响应头的 ASGI 中间件"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = self._is_https(scope)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}

                def _setdefault(name: bytes, value: bytes):
                    if name.lower() not in existing:
                        headers.append((name, value))
                        existing.add(name.lower())

                if is_https and settings.HSTS_MAX_AGE > 0:
                    _setdefault(
                        b"strict-transport-security",
                        f"max-age={settings.HSTS_MAX_AGE}; includeSubDomains".encode(),
                    )
                _setdefault(b"x-content-type-options", b"nosniff")
                _setdefault(b"x-frame-options", b"DENY")
                _setdefault(b"referrer-policy", b"strict-origin-when-cross-origin")
                _setdefault(b"x-xss-protection", b"0")
                _setdefault(
                    b"permissions-policy",
                    b"camera=(), microphone=(), geolocation=(), payment=()",
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)

    @staticmethod
    def _is_https(scope) -> bool:
        """识别请求是否走 HTTPS(支持 X-Forwarded-Proto 反代场景)"""
        if scope.get("scheme") == "https":
            return True
        headers = dict(scope.get("headers", []))
        forwarded_proto = headers.get(b"x-forwarded-proto", b"").decode().lower()
        return forwarded_proto == "https"


__all__ = ["SecurityHeadersMiddleware"]
