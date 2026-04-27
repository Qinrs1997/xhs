"""搜索提供商模块"""
from app.ai.services.search.providers.base import BaseSearchProvider
from app.ai.services.search.providers.duckduckgo import DuckDuckGoProvider
from app.ai.services.search.providers.tavily import TavilyProvider
from app.ai.services.search.providers.serper import SerperProvider
from app.ai.services.search.providers.searxng import SearXNGProvider
from app.ai.services.search.providers.brave import BraveSearchProvider

__all__ = [
    "BaseSearchProvider",
    "BraveSearchProvider",
    "DuckDuckGoProvider",
    "SearXNGProvider",
    "SerperProvider",
    "TavilyProvider",
]

# Provider 注册表
_PROVIDERS: dict[str, type[BaseSearchProvider]] = {
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "serper": SerperProvider,
    "searxng": SearXNGProvider,
    "brave": BraveSearchProvider,
}


def get_search_provider(name: str = "duckduckgo") -> BaseSearchProvider:
    """
    获取搜索提供商实例

    Args:
        name: 提供商名称 (duckduckgo, tavily, serper, searxng)

    Returns:
        搜索提供商实例
    """
    provider_class = _PROVIDERS.get(name.lower())
    if not provider_class:
        raise ValueError(f"不支持的搜索提供商: {name}，可选: {list(_PROVIDERS.keys())}")

    return provider_class()


def get_all_providers() -> dict[str, type[BaseSearchProvider]]:
    """获取所有已注册的 Provider 类"""
    return _PROVIDERS.copy()


def get_provider_meta_list(current_default: str = "duckduckgo") -> list[dict]:
    """
    获取所有 Provider 的元信息列表（前端选择器用）

    Args:
        current_default: 当前默认 Provider 名称

    Returns:
        Provider 元信息列表
    """
    meta_list = []
    for name, cls in _PROVIDERS.items():
        instance = cls()
        meta = instance.get_meta()
        meta["is_default"] = (name == current_default)
        # 尝试检测是否已配置可用
        try:
            instance.validate_config()
            meta["is_configured"] = True
        except Exception:
            meta["is_configured"] = not instance.requires_api_key
        meta_list.append(meta)
    return meta_list
