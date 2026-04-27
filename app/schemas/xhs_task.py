"""XHS 任务 Schema

定义 XHS 任务的请求和响应数据结构。
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态"""
    DRAFT = "draft"
    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==================== 页面内容结构 ====================

class PageContent(BaseModel):
    """单页内容"""
    page_num: int = Field(..., ge=1, description="页码")
    content: str = Field(..., description="页面文本内容")
    page_type: Optional[str] = Field("content", description="页面类型: cover/content/summary")
    image_url: Optional[str] = Field(None, description="图片 URL")
    thumbnail_url: Optional[str] = Field(None, description="缩略图 URL")
    original_url: Optional[str] = Field(None, description="原图 URL")
    image_prompt: Optional[str] = Field(None, description="图片生成提示词")
    layout: Optional[str] = Field(None, description="布局类型")
    title: Optional[str] = Field(None, description="页面标题")
    extra: Optional[dict] = Field(None, description="额外数据")


# ==================== 文案数据结构 ====================

class CopywritingData(BaseModel):
    """文案数据"""
    title: Optional[str] = Field(None, description="生成的标题")
    content: Optional[str] = Field(None, description="生成的正文")
    tags: Optional[List[str]] = Field(None, description="话题标签")
    emoji_title: Optional[str] = Field(None, description="备用 emoji 标题")


# ==================== 任务创建/更新 ====================

class XHSTaskCreate(BaseModel):
    """创建任务"""
    title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    topic: str = Field(..., min_length=1, description="主题/话题内容")
    pages: Optional[List[PageContent]] = Field(None, description="页面内容列表")
    style: Optional[str] = Field(None, max_length=50, description="风格类型")
    model: Optional[str] = Field(None, max_length=100, description="AI 模型")
    status: TaskStatus = Field(default=TaskStatus.DRAFT, description="任务状态")
    template_id: Optional[int] = Field(None, description="使用的模板 ID")


class XHSTaskUpdate(BaseModel):
    """更新任务"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="任务标题")
    topic: Optional[str] = Field(None, min_length=1, description="主题/话题内容")
    pages: Optional[List[PageContent]] = Field(None, description="页面内容列表")
    style: Optional[str] = Field(None, max_length=50, description="风格类型")
    model: Optional[str] = Field(None, max_length=100, description="AI 模型")
    status: Optional[TaskStatus] = Field(None, description="任务状态")
    error_message: Optional[str] = Field(None, description="错误信息")
    template_id: Optional[int] = Field(None, description="使用的模板 ID")


class XHSTaskSave(BaseModel):
    """
    保存任务（创建或更新）

    - 如果提供 task_id，则更新已有任务
    - 如果不提供 task_id，则创建新任务
    - autosave=true 时仅更新 pages + last_autosave_at（轻量保存）
    """
    task_id: Optional[int] = Field(None, description="任务 ID（更新时提供）")
    title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    topic: str = Field(..., min_length=1, description="主题/话题内容")
    pages: Optional[List[PageContent]] = Field(None, description="页面内容列表")
    style: Optional[str] = Field(None, max_length=50, description="风格类型")
    model: Optional[str] = Field(None, max_length=100, description="AI 模型")
    status: TaskStatus = Field(default=TaskStatus.DRAFT, description="任务状态")
    template_id: Optional[int] = Field(None, description="使用的模板 ID")
    autosave: bool = Field(default=False, description="是否为自动保存模式（仅更新 pages）")
    search_id: Optional[int] = Field(None, description="关联的搜索历史 ID")


# ==================== 任务响应 ====================

class XHSTaskResponse(BaseModel):
    """任务响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务 ID")
    user_id: int = Field(..., description="用户 ID")
    title: str = Field(..., description="任务标题")
    topic: str = Field(..., description="主题/话题内容")
    status: TaskStatus = Field(..., description="任务状态")
    pages: Optional[List[dict]] = Field(None, description="页面内容列表")
    style: Optional[str] = Field(None, description="风格类型")
    model: Optional[str] = Field(None, description="AI 模型")
    template_id: Optional[int] = Field(None, description="使用的模板 ID")
    copywriting: Optional[dict] = Field(None, description="生成的文案")
    page_count: int = Field(default=0, description="页面数量")
    total_tokens: int = Field(default=0, description="消耗的 Token 数")
    error_message: Optional[str] = Field(None, description="错误信息")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    last_autosave_at: Optional[datetime] = Field(None, description="最后自动保存时间")
    search_id: Optional[int] = Field(None, description="关联的搜索历史 ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class XHSTaskBrief(BaseModel):
    """任务简要信息（列表用，含 pages）"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务 ID")
    title: str = Field(..., description="任务标题")
    topic: str = Field(..., description="主题")
    status: TaskStatus = Field(..., description="任务状态")
    page_count: int = Field(default=0, description="页面数量")
    style: Optional[str] = Field(None, description="风格类型")
    template_id: Optional[int] = Field(None, description="模板 ID")
    has_copywriting: bool = Field(default=False, description="是否已生成文案")
    pages: Optional[List[dict]] = Field(None, description="页面内容列表")
    search_id: Optional[int] = Field(None, description="关联的搜索历史 ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class XHSTaskList(BaseModel):
    """任务列表响应"""
    items: List[XHSTaskBrief] = Field(..., description="任务列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    pages: int = Field(..., description="总页数")


# ==================== 操作响应 ====================

class TaskOperationResponse(BaseModel):
    """任务操作响应"""
    success: bool = Field(default=True, description="操作是否成功")
    task_id: Optional[int] = Field(None, description="任务 ID")
    message: Optional[str] = Field(None, description="消息")
    saved_at: Optional[datetime] = Field(None, description="保存时间")


# ==================== 查询参数 ====================

class XHSTaskQuery(BaseModel):
    """任务查询参数"""
    status: Optional[TaskStatus] = Field(None, description="状态筛选")
    keyword: Optional[str] = Field(None, description="关键词搜索（标题/主题）")
    start_date: Optional[datetime] = Field(None, description="开始日期")
    end_date: Optional[datetime] = Field(None, description="结束日期")

