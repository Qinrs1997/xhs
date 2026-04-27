"""HTTP 客户端门面(向后兼容)

搜索模块过去自建一套 `httpx.AsyncClient` 单例;现已统一到 `app.core.http_client`,
以复用连接池、超时和 limits 配置,避免多套"不同参数的客户端"并存。

保留 `HTTPClientManager` 类名与方法签名是为了:
- 现有 provider (`tavily/serper/brave/searxng`) 的 `HTTPClientManager.get_client()` 调用无需修改;
- `ai.facade` / `search.service` 中的 `HTTPClientManager.close()` 依旧可调用(已改为空操作,
  关闭工作由 lifespan 中的 `close_http_client()` 统一执行,避免重复关闭)。

后续新增调用方请直接使用 `app.core.http_client.get_http_client()`。
"""
from contextlib import asynccontextmanager

import httpx

from app.core.http_client import get_http_client
from app.core.logger import logger


class HTTPClientManager:
    """HTTP 客户端门面(BC 兼容,真实单例在 `app.core.http_client`)"""

    @classmethod
    async def get_client(
        cls,
        timeout: float = 30.0,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        """获取共享 HTTP 客户端(委托到 `app.core.http_client`)

        注:`timeout`/`follow_redirects` 参数保留是为了向后兼容,实际值由 core 客户端
        统一配置(`limits` + `timeout=30`)。如需逐请求覆盖,请在 `client.get/post`
        时传 `timeout=httpx.Timeout(...)`。
        """
        del timeout, follow_redirects
        return await get_http_client()

    @classmethod
    async def close(cls) -> None:
        """关闭逻辑已统一到 `lifespan` 中的 `close_http_client()`,本方法保留为空操作。"""
        logger.debug(
            "HTTPClientManager.close() 调用已忽略;共享 HTTP 客户端的关闭由 lifespan 统一负责"
        )

    @classmethod
    @asynccontextmanager
    async def session(cls):
        """向后兼容的 session 上下文;不会关闭共享客户端(因为它是全局复用的)"""
        client = await cls.get_client()
        try:
            yield client
        except Exception as e:
            logger.error("HTTP 请求异常: {}", e)
            raise

    @classmethod
    def is_initialized(cls) -> bool:
        """检查共享客户端是否已初始化"""
        from app.core import http_client as _core

        return _core._client is not None and not _core._client.is_closed
