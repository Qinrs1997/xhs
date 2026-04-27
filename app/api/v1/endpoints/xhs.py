"""XHS 生成 API 聚合路由

已拆分为：
- xhs_helpers.py   公共辅助函数
- xhs_generate.py  核心生成接口（大纲、文案、图片、提示词）
- xhs_batch.py     批量搜索生成接口
"""
from fastapi import APIRouter

from app.api.v1.endpoints.xhs_generate import router as generate_router
from app.api.v1.endpoints.xhs_batch import router as batch_router

router = APIRouter()
router.include_router(generate_router)
router.include_router(batch_router)
