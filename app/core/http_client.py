"""统一 HTTP 客户端管理

提供应用级别的 `httpx.AsyncClient` 单例,复用连接池,
避免每次请求都新建客户端(TCP 握手 + TLS 协商开销)。

超时策略(分层,更健康):
- `connect`  5s:握手失败快速 fallback,不等上游慢启动
- `read`    30s:允许长上游响应(AI/文件下载等)
- `write`   15s:大 body 上传
- `pool`     5s:从连接池取连接的排队时间(限流生效时更稳)

上层如需自定义可在调用点覆盖:`client.get(url, timeout=httpx.Timeout(...))`。

使用方式:
    from app.core.http_client import get_http_client, close_http_client

    client = await get_http_client()
    response = await client.get("https://example.com")

    # 应用关闭时
    await close_http_client()
"""
import httpx
from typing import Optional

from app.core.logger import logger


_client: Optional[httpx.AsyncClient] = None

# 默认分层超时,所有共享客户端调用都会继承
_DEFAULT_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=30.0,
    write=15.0,
    pool=5.0,
)


async def get_http_client() -> httpx.AsyncClient:
    """获取共享 HTTP 客户端(懒初始化,线程安全依赖 asyncio 事件循环)"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
        logger.debug("共享 HTTP 客户端已创建")
    return _client


async def close_http_client():
    """关闭共享 HTTP 客户端(应用关闭时调用)"""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.debug("共享 HTTP 客户端已关闭")
