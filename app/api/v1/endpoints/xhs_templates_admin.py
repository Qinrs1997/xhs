"""小红书模板 · 管理端 CRUD

端点：
- GET    /admin/xhs/templates              管理端分页列表（含下架、筛选 is_pro/price/author/关键词）
- GET    /admin/xhs/templates/{id}         管理端详情（含下架）
- POST   /admin/xhs/templates              创建模板
- PATCH  /admin/xhs/templates/{id}         部分更新
- DELETE /admin/xhs/templates/{id}         下架（软删），?hard=true 物理删除

仅超级管理员可用。
"""
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_superuser
from app.core.database import get_async_db
from app.core.exceptions import NotFoundError, BadRequestError
from app.crud.xhs_template import xhs_template
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()


# ==================== Schema ====================

class AdminTemplate(BaseModel):
    """管理端模板（包含所有字段）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    category: str
    cover_url: Optional[str] = None
    default_topic: str
    style_prompt: Optional[str] = None
    negative_style_prompt: Optional[str] = None
    content_prompt_template: Optional[str] = None
    page_count: int = 6
    example_pages: Optional[list] = None
    is_new: bool = False
    is_hot: bool = False
    use_count: int = 0
    price: int = 0
    is_pro: bool = False
    author_id: Optional[int] = None
    tags: Optional[List[str]] = None
    image_generation_mode: str = "per_page"
    image_grid_config: Optional[dict] = None
    sort_order: int = 0
    is_active: bool = True


class AdminTemplateList(BaseModel):
    items: List[AdminTemplate]
    total: int


class TemplateCreate(BaseModel):
    """创建模板"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    category: str = Field(..., min_length=1, max_length=50)
    cover_url: Optional[str] = Field(None, max_length=500)
    default_topic: str = Field(..., min_length=1, max_length=500)
    style_prompt: Optional[str] = None
    negative_style_prompt: Optional[str] = None
    content_prompt_template: Optional[str] = None
    page_count: int = Field(6, ge=1, le=20)
    example_pages: Optional[list] = None
    is_new: bool = False
    is_hot: bool = False
    price: int = Field(0, ge=0)
    is_pro: bool = False
    author_id: Optional[int] = None
    tags: Optional[List[str]] = None
    sort_order: int = 0
    is_active: bool = True
    image_generation_mode: Literal["per_page", "batch_grid"] = "per_page"
    image_grid_config: Optional[dict] = None


class TemplateUpdate(BaseModel):
    """部分更新（所有字段皆可选）"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    category: Optional[str] = Field(None, min_length=1, max_length=50)
    cover_url: Optional[str] = Field(None, max_length=500)
    default_topic: Optional[str] = Field(None, min_length=1, max_length=500)
    style_prompt: Optional[str] = None
    negative_style_prompt: Optional[str] = None
    content_prompt_template: Optional[str] = None
    page_count: Optional[int] = Field(None, ge=1, le=20)
    example_pages: Optional[list] = None
    is_new: Optional[bool] = None
    is_hot: Optional[bool] = None
    price: Optional[int] = Field(None, ge=0)
    is_pro: Optional[bool] = None
    author_id: Optional[int] = None
    tags: Optional[List[str]] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    image_generation_mode: Optional[Literal["per_page", "batch_grid"]] = None
    image_grid_config: Optional[dict] = None


# ==================== 端点 ====================

@router.get(
    "",
    response_model=Response[AdminTemplateList],
    summary="管理端模板列表",
)
async def admin_list_templates(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    category: Optional[str] = Query(None, description="分类筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用"),
    is_pro: Optional[bool] = Query(None, description="是否 VIP 专享"),
    author_id: Optional[int] = Query(None, description="作者 user_id"),
    keyword: Optional[str] = Query(None, description="模板名关键字(模糊)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Any:
    items, total = await xhs_template.get_admin_list(
        db,
        category=category,
        is_active=is_active,
        is_pro=is_pro,
        author_id=author_id,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return Response(
        code=200, success=True, message="获取成功",
        data=AdminTemplateList(
            items=[AdminTemplate.model_validate(t) for t in items],
            total=total,
        ),
    )


@router.get(
    "/{template_id}",
    response_model=Response[AdminTemplate],
    summary="管理端模板详情（含下架）",
)
async def admin_get_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    template_id: int,
) -> Any:
    tpl = await xhs_template.get_by_id(
        db, template_id=template_id, include_inactive=True
    )
    if not tpl:
        raise NotFoundError("模板不存在")
    return Response(
        code=200, success=True, message="获取成功",
        data=AdminTemplate.model_validate(tpl),
    )


@router.post(
    "",
    response_model=Response[AdminTemplate],
    status_code=status.HTTP_201_CREATED,
    summary="创建模板",
)
async def admin_create_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    payload: TemplateCreate,
) -> Any:
    tpl = await xhs_template.create(db, data=payload.model_dump(exclude_unset=False))
    return Response(
        code=200, success=True, message="创建成功",
        data=AdminTemplate.model_validate(tpl),
    )


@router.patch(
    "/{template_id}",
    response_model=Response[AdminTemplate],
    summary="更新模板",
)
async def admin_update_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    template_id: int,
    payload: TemplateUpdate,
) -> Any:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise BadRequestError("请求体不能为空")
    tpl = await xhs_template.update(db, template_id=template_id, data=data)
    if not tpl:
        raise NotFoundError("模板不存在")
    return Response(
        code=200, success=True, message="更新成功",
        data=AdminTemplate.model_validate(tpl),
    )


@router.delete(
    "/{template_id}",
    response_model=Response[dict],
    summary="下架(软删)/删除(硬删)模板",
)
async def admin_delete_template(
    *,
    db: AsyncSession = Depends(get_async_db),
    _admin: User = Depends(get_current_superuser),
    template_id: int,
    hard: bool = Query(False, description="true=物理删除；默认 false 仅下架"),
) -> Any:
    ok = await xhs_template.delete(db, template_id=template_id, hard=hard)
    if not ok:
        raise NotFoundError("模板不存在")
    return Response(
        code=200, success=True,
        message="已删除" if hard else "已下架",
        data={"template_id": template_id, "hard": hard},
    )
