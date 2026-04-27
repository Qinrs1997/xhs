"""公告相关的 Pydantic schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class TargetType(str, Enum):
    """公告发送范围类型"""
    ALL = "all"       # 所有人
    DEPT = "dept"     # 指定部门


class AnnouncementBase(BaseModel):
    """公告基础信息"""
    title: str = Field(..., max_length=200, description="公告标题")
    content: str = Field(..., description="公告内容")
    type: str = Field(default="notice", description="公告类型: notice(通知), emergency(紧急), update(更新), event(活动)")
    is_published: bool = Field(default=False, description="是否发布")


class AnnouncementCreate(AnnouncementBase):
    """创建公告"""
    published_at: Optional[datetime] = Field(None, description="发布时间（如果不传且 is_published=True 则默认为当前时间）")
    target_type: TargetType = Field(default=TargetType.ALL, description="发送范围: all(所有人), dept(指定部门)")
    dept_ids: Optional[List[int]] = Field(None, description="目标部门ID列表（当 target_type='dept' 时必填）")


class AnnouncementUpdate(BaseModel):
    """更新公告"""
    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = None
    type: Optional[str] = None
    is_published: Optional[bool] = None
    published_at: Optional[datetime] = None
    target_type: Optional[TargetType] = Field(None, description="发送范围")
    dept_ids: Optional[List[int]] = Field(None, description="目标部门ID列表")


class DepartmentBrief(BaseModel):
    """部门简要信息（用于公告响应）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str


class AnnouncementOut(AnnouncementBase):
    """公告响应数据"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    author_name: str
    published_at: Optional[datetime]
    target_type: TargetType = Field(default=TargetType.ALL, description="发送范围")
    target_dept_ids: List[int] = Field(default=[], description="目标部门ID列表")
    created_at: datetime
    updated_at: datetime


class AnnouncementDetail(AnnouncementOut):
    """公告详情（包含部门信息）"""
    target_departments: List[DepartmentBrief] = Field(default=[], description="目标部门列表")


class AnnouncementList(BaseModel):
    """公告列表数据结构"""
    total: int
    items: List[AnnouncementOut]
