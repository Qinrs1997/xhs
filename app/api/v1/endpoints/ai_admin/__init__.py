"""AI 管理接口子包（仅管理员可用）

按职责拆分为 6 个子模块，对外仍以 `ai_admin.router` 统一导出：

- reload.py          — POST /reload-config
- global_config.py   — GET / PATCH /config
- providers.py       — /providers CRUD + /providers/{id}/set-default
- testing.py         — POST /providers/{id}/test
- usage.py           — GET /usage/stats + /usage/by-model
- search_key.py      — GET/PATCH /search/tavily + POST /search/tavily/test
"""
from fastapi import APIRouter

from .global_config import router as global_config_router
from .providers import router as providers_router
from .reload import router as reload_router
from .search_key import router as search_key_router
from .testing import router as testing_router
from .usage import router as usage_router

router = APIRouter()
router.include_router(reload_router)
router.include_router(global_config_router)
router.include_router(providers_router)
router.include_router(testing_router)
router.include_router(usage_router)
router.include_router(search_key_router)

__all__ = ["router"]
