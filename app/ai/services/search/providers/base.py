"""搜索提供商基类

定义搜索提供商必须实现的接口和元信息。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.ai.schemas.search import SearchResult


@dataclass
class SearchProviderConfig:
    """搜索服务商配置"""
    name: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


class BaseSearchProvider(ABC):
    """搜索提供商抽象基类

    所有搜索提供商必须实现此接口。

    实现新提供商时：
    1. 继承此类
    2. 声明类属性（name, display_name, description 等元信息）
    3. 实现 search() 方法
    4. 在 __init__.py 中注册
    """

    # ---- 基础标识 ----
    name: str = "base"
    display_name: str = "基础搜索"
    description: str = ""

    # ---- 功能声明 ----
    requires_api_key: bool = False
    supports_news: bool = False
    supports_images: bool = False
    max_results_limit: int = 20

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """
        执行搜索

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            **kwargs: 额外参数（如 search_depth、region）

        Returns:
            搜索结果列表
        """

    def validate_config(self) -> None:
        """验证配置（可选实现）"""

    def get_meta(self) -> dict:
        """获取 Provider 元信息（用于前端展示）"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "requires_api_key": self.requires_api_key,
            "supports_news": self.supports_news,
            "supports_images": self.supports_images,
            "max_results_limit": self.max_results_limit,
        }
