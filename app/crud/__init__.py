"""CRUD 操作模块 (统一异步版)

该模块已全面重构为异步驱动。所有的 CRUD 实例（如 user, role）现在均为异步对象。
同步操作仅通过 app.core.database._get_sync_db 在极端启动场景或 Alembic 中内部使用。

使用示例：
    from app.crud import user, role
    user_obj = await user.get(db, id=1)

    # 定义新的软删除 CRUD 类
    from app.crud import CRUDBaseSoftDelete
    class CRUDArticle(CRUDBaseSoftDelete[Article, ArticleCreate, ArticleUpdate]):
        pass
"""

# 核心异步基类
from app.crud.base import CRUDBase
from app.crud.base_soft_delete import CRUDBaseSoftDelete

# 业务 CRUD 实例
from app.crud.user import user
from app.crud.role import role
from app.crud.announcement import announcement
from app.crud.audit_log import audit_log_crud
from app.crud.prompt import prompt_crud
from app.crud.search_history import search_history_crud

__all__ = [
    # 基类
    "CRUDBase",
    "CRUDBaseSoftDelete",
    "announcement",
    "audit_log_crud",
    "prompt_crud",
    "role",
    "search_history_crud",
    # 实例
    "user",
]
