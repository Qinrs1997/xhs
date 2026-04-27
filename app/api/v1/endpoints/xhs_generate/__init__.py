"""XHS 生成 API —— 核心生成接口

按职责拆分为 4 个子模块，对外仍以 `xhs_generate.router` 统一导出：

- outline.py  — POST /outline（大纲生成 + 自动建 draft 任务）
- content.py  — POST /content + /copywriting/generate（文案生成）
- image.py    — POST /image/stream（SSE）+ /image/regenerate（单页重生）
- prompts.py  — POST /prompts（批量）+ /prompt/optimize（单条）
"""
from fastapi import APIRouter

from .content import router as content_router
from .image import router as image_router
from .outline import router as outline_router
from .prompts import router as prompts_router

router = APIRouter()
router.include_router(outline_router)
router.include_router(content_router)
router.include_router(image_router)
router.include_router(prompts_router)

__all__ = ["router"]
