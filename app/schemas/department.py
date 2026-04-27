"""部门管理 Schema

定义部门的请求和响应数据结构。
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


# ==================== 部门 Schema ====================

class DepartmentBase(BaseModel):
    """部门基础信息"""
    name: str = Field(..., min_length=1, max_length=100, description="部门名称")
    code: str = Field(..., min_length=1, max_length=50, description="部门编码")
    parent_id: Optional[int] = Field(None, description="父部门ID")
    description: Optional[str] = Field(None, description="部门描述")
    sort_order: int = Field(default=0, description="排序顺序")
    leader_id: Optional[int] = Field(None, description="部门负责人ID")


class DepartmentCreate(DepartmentBase):
    """创建部门"""
    pass


class DepartmentUpdate(BaseModel):
    """更新部门"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="部门名称")
    code: Optional[str] = Field(None, min_length=1, max_length=50, description="部门编码")
    parent_id: Optional[int] = Field(None, description="父部门ID")
    description: Optional[str] = Field(None, description="部门描述")
    sort_order: Optional[int] = Field(None, description="排序顺序")
    leader_id: Optional[int] = Field(None, description="部门负责人ID")
    is_active: Optional[bool] = Field(None, description="是否启用")


class DepartmentResponse(BaseModel):
    """部门响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="部门ID")
    name: str = Field(..., description="部门名称")
    code: str = Field(..., description="部门编码")
    parent_id: Optional[int] = Field(None, description="父部门ID")
    level: int = Field(..., description="层级")
    sort_order: int = Field(..., description="排序顺序")
    leader_id: Optional[int] = Field(None, description="部门负责人ID")
    description: Optional[str] = Field(None, description="部门描述")
    is_active: bool = Field(..., description="是否启用")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class DepartmentBrief(BaseModel):
    """部门简要信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    level: int


class DepartmentTree(BaseModel):
    """部门树节点"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    parent_id: Optional[int] = None
    level: int
    sort_order: int
    is_active: bool
    children: List["DepartmentTree"] = Field(default_factory=list, description="子部门")


# ==================== 用户-部门关联 Schema ====================

class UserDepartmentAssign(BaseModel):
    """分配用户到部门"""
    user_id: int = Field(..., description="用户ID")
    department_id: int = Field(..., description="部门ID")
    is_primary: bool = Field(default=False, description="是否主部门")
    position: Optional[str] = Field(None, max_length=100, description="职位")


class UserDepartmentBatchAssign(BaseModel):
    """批量分配部门"""
    user_id: int = Field(..., description="用户ID")
    department_ids: List[int] = Field(..., min_length=1, description="部门ID列表")
    primary_department_id: Optional[int] = Field(None, description="主部门ID")
    clear_existing: bool = Field(
        default=False,
        description="是否清除现有部门（false=追加模式，true=替换模式）"
    )


class UserDepartmentResponse(BaseModel):
    """用户部门关联响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    department_id: int
    is_primary: bool
    position: Optional[str] = None
    department: Optional[DepartmentBrief] = None


class DepartmentUserResponse(BaseModel):
    """部门下的用户"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    is_primary: bool
    position: Optional[str] = None
    username: str
    full_name: Optional[str] = None
    email: str


# ==================== 列表响应 ====================

class DepartmentList(BaseModel):
    """部门列表"""
    items: List[DepartmentResponse]
    total: int
