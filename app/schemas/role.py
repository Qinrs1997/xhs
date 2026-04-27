"""角色相关 Pydantic Schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class RoleBase(BaseModel):
    """角色基础信息"""
    name: str = Field(..., min_length=2, max_length=50, description="角色名称（唯一）")
    description: Optional[str] = Field(None, max_length=255, description="角色描述")
    is_active: Optional[bool] = Field(True, description="是否启用")


class RoleCreate(RoleBase):
    """创建角色"""
    pass


class RoleUpdate(BaseModel):
    """更新角色"""
    name: Optional[str] = Field(None, min_length=2, max_length=50, description="角色名称")
    description: Optional[str] = Field(None, max_length=255, description="角色描述")
    is_active: Optional[bool] = Field(None, description="是否启用")


class Role(RoleBase):
    """角色响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class RoleList(BaseModel):
    """角色列表"""
    total: int = Field(..., description="总数")
    items: list[Role] = Field(..., description="角色列表")

