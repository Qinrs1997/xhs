"""通用工具函数

提供一些通用的工具函数。
日志中间件已移至 app.core.middleware 模块。
"""

from fastapi import Request


from app.core.logger import logger


def log_request(prefix: str = "request", max_body: int = 2000):
    """
    请求日志装饰器（依赖形式）

    用于记录特定端点的请求详情。

    用法：
        from fastapi import Depends
        from app.core.utils import log_request

        @router.get("/", dependencies=[Depends(log_request("admin action"))])
        async def demo(): ...
    """

    async def _logger(request: Request) -> None:
        query = dict(request.query_params)
        path_params = request.path_params

        try:
            body_bytes = await request.body()
            body = body_bytes.decode("utf-8") if body_bytes else ""
        except Exception:
            body = "<unreadable>"

        logger.info(
            "{} | method={} path={} query={} path_params={} body={}",
            prefix,
            request.method,
            request.url.path,
            query,
            path_params,
            body[:max_body],  # 避免日志过大
        )

    return _logger


def mask_sensitive_data(data: dict, fields: list[str] | None = None) -> dict:
    """
    掩码敏感数据

    将指定字段的值替换为 "***"

    Args:
        data: 原始数据字典
        fields: 需要掩码的字段列表

    Returns:
        掩码后的数据字典

    使用示例：
        data = {"username": "admin", "password": "123456"}
        masked = mask_sensitive_data(data, ["password"])
        # {"username": "admin", "password": "***"}
    """
    if fields is None:
        fields = ["password", "token", "secret", "key", "authorization"]

    masked = data.copy()
    for field in fields:
        if field in masked:
            masked[field] = "***"

    return masked


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    截断字符串

    如果字符串超过指定长度，截断并添加后缀。

    Args:
        s: 原始字符串
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的字符串
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def get_client_ip(request: Request) -> str:
    """
    获取客户端真实 IP 地址

    支持代理场景，按优先级检查：
    1. X-Forwarded-For 头（多级代理取第一个）
    2. X-Real-IP 头
    3. 直连客户端 IP

    Args:
        request: FastAPI Request 对象

    Returns:
        客户端 IP 地址，获取失败返回 "unknown"
    """
    # 优先从代理头获取
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # 直接获取客户端 IP
    if request.client:
        return request.client.host

    return "unknown"


def get_client_ip_from_scope(scope: dict, headers: dict) -> str:
    """
    从 ASGI scope 获取客户端 IP（用于纯 ASGI 中间件）

    Args:
        scope: ASGI scope 字典
        headers: 已解析的 headers 字典（key 为 bytes）

    Returns:
        客户端 IP 地址
    """
    # 优先从代理头获取
    forwarded_for = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = headers.get(b"x-real-ip", b"").decode()
    if real_ip:
        return real_ip

    # 直接获取客户端 IP
    client = scope.get("client")
    if client:
        return client[0]

    return "unknown"
