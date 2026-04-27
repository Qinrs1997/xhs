"""搜索服务模块

拆分后的搜索服务结构：
- __init__.py       本文件，导出主要类
- service.py        SearchService 主类
- providers/        搜索服务商实现
  - base.py         搜索提供商基类
  - brave.py        Brave Search 实现（推荐，独立索引）
  - duckduckgo.py   DuckDuckGo 实现（ddgs 库）
  - tavily.py       Tavily 实现
  - serper.py       Serper 实现
  - searxng.py      SearXNG 元搜索引擎实现
- http_client.py    HTTP 客户端管理
"""
from app.ai.services.search.service import SearchService
from app.ai.services.search.http_client import HTTPClientManager

__all__ = ["HTTPClientManager", "SearchService"]
