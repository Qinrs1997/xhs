"""用户相关的 Pydantic schemas"""
import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator


# ==================== 部门简要信息（用于用户响应） ====================

class UserDepartmentInfo(BaseModel):
    """用户的部门信息"""
    model_config = ConfigDict(from_attributes=True)

    department_id: int = Field(..., description="部门ID")
    department_name: str = Field(..., description="部门名称")
    department_code: str = Field(..., description="部门编码")
    is_primary: bool = Field(default=False, description="是否主部门")
    position: Optional[str] = Field(None, description="职位")


# ==================== 用户基础 Schema ====================

class UserBase(BaseModel):
    """用户基础信息"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    full_name: Optional[str] = Field(None, max_length=100, description="全名/昵称")
    phone: Optional[str] = Field(None, max_length=20, description="手机号")
    avatar: Optional[str] = Field(None, max_length=255, description="用户头像")
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")


def _validate_password_strength(password: str) -> str:
    """统一密码强度校验"""
    if len(password) < 6:
        raise ValueError("密码长度不能少于 6 位")
    if len(password) > 50:
        raise ValueError("密码长度不能超过 50 位")
    if not re.search(r'[a-zA-Z]', password):
        raise ValueError("密码必须包含字母")
    if not re.search(r'\d', password):
        raise ValueError("密码必须包含数字")
    return password


# 用户创建 Schema（内部使用，不需要验证码）
class UserCreate(UserBase):
    """创建用户（内部/管理员使用）"""
    password: str = Field(..., min_length=6, max_length=50, description="密码（需包含字母和数字）")

    @field_validator('password')
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


# 用户注册 Schema（前端注册，需要邮箱验证码）
class UserRegister(UserBase):
    """用户注册（需邮箱验证码）"""
    password: str = Field(..., min_length=6, max_length=50, description="密码（需包含字母和数字）")
    verify_code: str = Field(..., min_length=4, max_length=8, description="邮箱验证码")
    invite_code: Optional[str] = Field(None, max_length=20, description="邀请码（可选）")

    @field_validator('password')
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


# 发送验证码请求
class SendVerifyCodeRequest(BaseModel):
    """发送邮箱验证码"""
    email: EmailStr = Field(..., description="接收验证码的邮箱")


# 用户更新 Schema
class UserUpdate(BaseModel):
    """更新用户"""
    email: Optional[EmailStr] = Field(None, description="邮箱")
    full_name: Optional[str] = Field(None, max_length=100, description="全名/昵称")
    phone: Optional[str] = Field(None, max_length=20, description="手机号")
    avatar: Optional[str] = Field(None, max_length=255, description="用户头像")
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")
    password: Optional[str] = Field(None, min_length=6, max_length=50, description="密码")
    is_active: Optional[bool] = Field(None, description="是否激活")


# 用户返回 Schema
class UserInDB(UserBase):
    """数据库中的用户（包含所有字段）"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


# 用户响应 Schema（不包含敏感信息）
class User(UserBase):
    """用户响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime


# 用户响应 Schema（包含部门信息）
class UserWithDepartments(User):
    """用户响应（包含部门信息）"""
    departments: List[UserDepartmentInfo] = Field(default=[], description="所属部门列表")
    primary_department: Optional[UserDepartmentInfo] = Field(None, description="主部门")


# 用户列表响应
class UserList(BaseModel):
    """用户列表"""
    total: int = Field(..., description="总数")
    items: list[User] = Field(..., description="用户列表")


# 用户列表响应（包含部门）
class UserListWithDepartments(BaseModel):
    """用户列表（包含部门信息）"""
    total: int = Field(..., description="总数")
    items: list[UserWithDepartments] = Field(..., description="用户列表")


# 登录相关
class Token(BaseModel):
    """Token 响应

    同时支持 OAuth2 标准字段和驼峰命名字段，
    access_token 和 token_type 用于 Swagger UI 认证，
    accessToken 等驼峰字段用于前端。
    """
    # OAuth2 标准字段（Swagger UI 需要这些字段）
    access_token: str = Field(..., description="访问令牌（OAuth2 标准）")
    token_type: str = Field(default="bearer", description="令牌类型（OAuth2 标准）")

    # 以下为扩展字段,供前端使用;camelCase 是前端契约字段名,不能改为 snake_case
    accessToken: str = Field(..., description="访问令牌")  # noqa: N815 -- 前端契约字段
    refreshToken: str = Field(..., description="刷新令牌")  # noqa: N815 -- 前端契约字段
    expires: str = Field(..., description="过期时间")
    username: str = Field(..., description="用户名")
    nickname: Optional[str] = Field(None, description="用户昵称")
    avatar: Optional[str] = Field(None, description="用户头像")
    roles: list[str] = Field(default=[], description="角色列表")
    permissions: list[str] = Field(default=[], description="权限列表")


class TokenData(BaseModel):
    """Token 数据"""
    user_id: Optional[int] = None


class UserLogin(BaseModel):
    """用户登录"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


# ==================== 菜单偏好设置 ====================

class MenuPreferencesUpdate(BaseModel):
    """更新菜单偏好请求"""
    hidden_menus: List[str] = Field(
        default=[],
        description="用户隐藏的菜单路径列表",
        examples=[["/xhs", "/system/logs"]]
    )


class MenuPreferencesResponse(BaseModel):
    """菜单偏好响应"""
    hidden_menus: List[str] = Field(
        default=[],
        description="用户隐藏的菜单路径列表"
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="最后更新时间"
    )


# ==================== 密码修改/重置 ====================

class ChangePassword(BaseModel):
    """修改密码（需验证旧密码）"""
    old_password: str = Field(..., min_length=1, description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码（需包含字母和数字）")
    confirm_password: str = Field(..., min_length=6, max_length=50, description="确认新密码")

    @field_validator('new_password')
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class AdminResetPassword(BaseModel):
    """管理员重置用户密码"""
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码（需包含字母和数字）")

    @field_validator('new_password')
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class ForgotPasswordRequest(BaseModel):
    """忘记密码 - 请求重置"""
    email: EmailStr = Field(..., description="注册邮箱")


class ResetPasswordConfirm(BaseModel):
    """忘记密码 - 确认重置（通过邮箱验证码）"""
    email: EmailStr = Field(..., description="注册邮箱")
    verify_code: str = Field(..., min_length=4, max_length=8, description="邮箱验证码")
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码（需包含字母和数字）")
    confirm_password: str = Field(..., min_length=6, max_length=50, description="确认新密码")

    @field_validator('new_password')
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求

    同时兼容前端 camelCase（refreshToken）与后端 snake_case（refresh_token）。
    """
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: str = Field(..., alias="refreshToken", description="刷新令牌")
