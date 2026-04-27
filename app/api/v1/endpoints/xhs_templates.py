"""小红书模板 API

接口列表：
- GET /templates           获取模板列表（含分类统计）
- GET /templates/{id}      获取模板详情
"""
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict

from app.core.database import get_async_db
from app.core.exceptions import NotFoundError
from app.api.deps import get_current_active_user
from app.models.user import User
from app.crud.xhs_template import xhs_template, CATEGORY_LABELS
from app.schemas.response import Response

router = APIRouter()


# ==================== 响应 Schema ====================

class TemplateItem(BaseModel):
    """模板列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    category: str
    cover_url: Optional[str] = None
    default_topic: str
    style_prompt: Optional[str] = None
    # 负向风格约束,用户端生图时和 style_prompt 一起透传到
    # /xhs/image/stream, 作为硬性禁出元素。之前漏了这个字段, 用户端
    # 创作时拿不到 → 模板"禁止XX"约束全废。
    negative_style_prompt: Optional[str] = None
    content_prompt_template: Optional[str] = None
    page_count: int
    sort_order: int = 0
    is_active: bool = True
    is_new: bool = False
    is_hot: bool = False
    use_count: int = 0
    # 商业化字段
    price: int = 0
    is_pro: bool = False
    author_id: Optional[int] = None
    tags: Optional[List[str]] = None
    # 生图模式与网格配置。这两个字段管理端 AdminTemplate 是全的, 但
    # 用户端这里之前漏了 → 前端 selectedTemplate.image_generation_mode
    # 永远 undefined, effectiveMode 永远兜底到 per_page, 即使后台
    # 已经把模板设成 batch_grid 也不生效。
    image_generation_mode: str = "per_page"
    image_grid_config: Optional[dict] = None


class TemplateDetail(TemplateItem):
    """模板详情（含示例页面）"""
    example_pages: Optional[list] = None


class CategoryStat(BaseModel):
    key: str
    label: str
    count: int


class TemplateListData(BaseModel):
    items: List[TemplateItem]
    categories: List[CategoryStat]


# ==================== API 端点 ====================

@router.get(
    "",
    response_model=Response[TemplateListData],
    summary="获取模板列表",
    description="获取所有启用的模板，支持按分类筛选。",
)
async def list_templates(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    category: Optional[str] = Query(None, description="按分类筛选: food/fashion/travel 等"),
) -> Any:
    """获取模板列表（含分类统计）"""
    items = await xhs_template.get_active_list(db, category=category)
    category_stats = await xhs_template.get_category_stats(db)

    # 用 Schema 自动转换 ORM 对象
    template_items = [TemplateItem.model_validate(tpl) for tpl in items]

    categories = [
        CategoryStat(
            key=stat["key"],
            label=CATEGORY_LABELS.get(stat["key"], stat["key"]),
            count=stat["count"],
        )
        for stat in category_stats
    ]

    return Response(
        code=200, success=True, message="获取成功",
        data=TemplateListData(items=template_items, categories=categories),
    )


@router.get(
    "/{template_id}",
    response_model=Response[TemplateDetail],
    summary="获取模板详情",
    description="获取指定模板的详情，包含示例页面。",
)
async def get_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    template_id: int,
) -> Any:
    """获取模板详情"""
    tpl = await xhs_template.get_by_id(db, template_id=template_id)
    if not tpl:
        raise NotFoundError("模板不存在")

    detail = TemplateDetail.model_validate(tpl)
    if detail.example_pages is None:
        detail.example_pages = []

    return Response(code=200, success=True, message="获取成功", data=detail)
