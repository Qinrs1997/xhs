"""AI API 端点 — 路由聚合器

将各 AI 子模块的 router 聚合在一起：
- ai_chat.py         → 聊天 (chat, chat/stream)
- ai_search.py       → 搜索 + 总结 (summary, search)
- ai_image.py        → 图像生成 (image/generate)
- ai_prompts.py      → 提示词管理 (prompts CRUD + preview)
- ai_conversations.py → 会话管理 (conversations CRUD)
- ai_tools.py        → 工具 (health, stats, config)
- search_history.py  → 搜索历史
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    ai_chat,
    ai_search,
    ai_image,
    ai_prompts,
    ai_conversations,
    ai_tools,
    search_history,
)

router = APIRouter()

router.include_router(ai_chat.router, tags=["AI 聊天"])
router.include_router(ai_search.router, tags=["AI 搜索/总结"])
router.include_router(ai_image.router, tags=["AI 图像生成"])
router.include_router(ai_prompts.router, tags=["AI 提示词"])
router.include_router(search_history.router, tags=["搜索历史"])
router.include_router(ai_conversations.router, tags=["AI 会话管理"])
router.include_router(ai_tools.router, tags=["AI 工具"])
