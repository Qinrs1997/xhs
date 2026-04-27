"""搜索历史 Schema

定义搜索历史的请求/响应数据结构。
"""
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, ConfigDict


# ==================== 内部创建/更新 ====================

class SearchHistoryCreate(BaseModel):
    """创建搜索历史记录（内部使用）"""
    query: str = Field(..., max_length=500, description="搜索查询关键词")
    summary: Optional[str] = Field(None, description="摘要（前200字截断）")
    full_summary: Optional[str] = Field(None, description="完整摘要内容")
    sources_count: int = Field(default=0, description="搜索来源数量")
    status: str = Field(default="completed", description="状态: completed/generating/failed")
    search_results: Optional[Any] = Field(None, description="搜索结果列表 (JSON)")
    metadata_info: Optional[dict] = Field(None, description="搜索元数据: model/latency_ms/search_provider 等")


class SearchHistoryUpdate(BaseModel):
    """更新搜索历史记录（内部使用）"""
    summary: Optional[str] = Field(None, description="摘要")
    full_summary: Optional[str] = Field(None, description="完整摘要")
    sources_count: Optional[int] = Field(None, description="搜索来源数量")
    status: Optional[str] = Field(None, description="状态")
    search_results: Optional[Any] = Field(None, description="搜索结果列表")
    metadata_info: Optional[dict] = Field(None, description="搜索元数据")


# ==================== 关联任务简要 ====================

class GeneratedTaskBrief(BaseModel):
    """关联的生成任务简要信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="任务 ID")
    title: str = Field(..., description="任务标题")
    status: str = Field(..., description="任务状态")
    created_at: datetime = Field(..., description="创建时间")


# ==================== API 响应 ====================

class SearchHistoryItem(BaseModel):
    """搜索历史列表项（不含 full_summary 和 search_results 详情）"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="搜索记录 ID")
    query: str = Field(..., description="搜索查询")
    summary: Optional[str] = Field(None, description="摘要（前200字）")
    sources_count: int = Field(default=0, description="搜索来源数量")
    status: str = Field(default="completed", description="状态")
    generated_tasks_count: int = Field(default=0, description="关联任务数量")
    generated_task_ids: List[int] = Field(default_factory=list, description="关联任务 ID 列表")
    created_at: datetime = Field(..., description="创建时间")
    metadata_info: Optional[dict] = Field(None, description="搜索元数据")


class SearchHistoryDetail(BaseModel):
    """搜索历史详情（含完整内容和关联任务列表）"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="搜索记录 ID")
    query: str = Field(..., description="搜索查询")
    summary: Optional[str] = Field(None, description="摘要（前200字）")
    full_summary: Optional[str] = Field(None, description="完整摘要")
    sources_count: int = Field(default=0, description="搜索来源数量")
    status: str = Field(default="completed", description="状态")
    results: Optional[List[dict]] = Field(None, description="搜索结果列表")
    generated_tasks_count: int = Field(default=0, description="关联任务数量")
    generated_task_ids: List[int] = Field(default_factory=list, description="关联任务 ID 列表")
    generated_tasks: List[GeneratedTaskBrief] = Field(default_factory=list, description="关联任务详情列表")
    created_at: datetime = Field(..., description="创建时间")
    metadata_info: Optional[dict] = Field(None, description="搜索元数据")


# ==================== 进度状态（可选端点） ====================

class StepStatus(BaseModel):
    """步骤状态"""
    name: str = Field(..., description="步骤名称")
    status: str = Field(..., description="步骤状态: done/running/pending")
    duration_ms: Optional[int] = Field(None, description="步骤耗时(ms)")
    progress: Optional[str] = Field(None, description="进度（如 3/5）")


class SearchHistoryStatusResponse(BaseModel):
    """搜索生成进度响应"""
    status: str = Field(..., description="状态: completed/generating/failed")
    progress: int = Field(default=0, description="总进度百分比")
    current_step: Optional[str] = Field(None, description="当前步骤描述")
    steps: List[StepStatus] = Field(default_factory=list, description="步骤列表")
