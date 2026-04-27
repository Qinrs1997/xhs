"""用户提示词 Schema

定义用户自定义提示词的请求和响应模型。
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


# ==================== 创建 ====================

class UserPromptCreate(BaseModel):
    """创建用户提示词请求"""
    key: Optional[str] = Field(
        default="",
        description="模板 key（同一用户下唯一，不传或为 null 则自动生成）",
        max_length=100,
    )
    name: str = Field(
        description="显示名称",
        min_length=1,
        max_length=100
    )
    content: str = Field(
        description="提示词内容，支持 {{variable}} 变量",
        min_length=1,
        max_length=50000
    )
    description: str = Field(
        default="",
        description="描述说明",
        max_length=1000
    )
    category: str = Field(
        default="custom",
        description="分类: custom, chat, summary, search, image, role",
        max_length=50
    )
    variables: Optional[dict] = Field(
        default=None,
        description="变量定义，如 {'name': {'type': 'string', 'required': true}}"
    )
    extends: Optional[list[str]] = Field(
        default=None,
        description="继承的模板 key 列表"
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="标签列表"
    )
    is_public: bool = Field(
        default=False,
        description="是否公开给所有用户（仅管理员可设置）"
    )
    image_config: Optional[dict] = Field(
        default=None,
        description="图片生成专用配置"
    )

    @field_validator("key", mode="before")
    @classmethod
    def validate_key(cls, v) -> str:
        """key 为空/null 时返回空字符串(由端点自动生成);非空时接受字母/数字/_/-/`/`

        与系统内置模板命名风格(如 `xhs/content`)保持一致,允许斜杠分段;
        前端 `views/ai/prompt/index.vue` 的正则已含 `/`,此处对齐。
        """
        if v is None:
            return ""
        v = str(v).strip()
        if v and not re.match(r"^[a-zA-Z0-9_\-/]+$", v):
            raise ValueError(
                "key 只能包含英文字母、数字、下划线、短横线和斜杠(用于分段,如 xhs/content)"
            )
        if v and (v.startswith("/") or v.endswith("/") or "//" in v):
            raise ValueError("key 不能以斜杠开头/结尾,也不能包含连续斜杠")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "my_anime_style",
                "name": "我的动漫风格",
                "content": "Create an anime-style illustration of {{subject}}, vibrant colors, cel shading",
                "description": "生成日系动漫风格图片",
                "category": "image",
                "variables": {
                    "subject": {
                        "type": "string",
                        "required": True,
                        "description": "画面主体",
                    }
                },
                "tags": ["image", "anime"],
            }
        }
    )


# ==================== 更新 ====================

class UserPromptUpdate(BaseModel):
    """更新用户提示词请求"""
    name: Optional[str] = Field(
        default=None,
        description="显示名称",
        min_length=1,
        max_length=100
    )
    content: Optional[str] = Field(
        default=None,
        description="提示词内容",
        min_length=1,
        max_length=50000
    )
    description: Optional[str] = Field(
        default=None,
        description="描述说明",
        max_length=1000
    )
    category: Optional[str] = Field(
        default=None,
        description="分类",
        max_length=50
    )
    variables: Optional[dict] = Field(
        default=None,
        description="变量定义"
    )
    extends: Optional[list[str]] = Field(
        default=None,
        description="继承的模板"
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="标签列表"
    )
    is_public: Optional[bool] = Field(
        default=None,
        description="是否公开（仅管理员可设置）"
    )
    image_config: Optional[dict] = Field(
        default=None,
        description="图片生成配置"
    )


# ==================== 响应 ====================

class UserPromptResponse(BaseModel):
    """用户提示词响应"""
    id: int = Field(description="提示词 ID")
    key: str = Field(description="模板 key")
    full_key: str = Field(description="完整 key（带前缀）")
    user_id: Optional[int] = Field(description="创建者 ID")
    is_public: bool = Field(description="是否公开")
    name: str = Field(description="显示名称")
    description: str = Field(description="描述")
    category: str = Field(description="分类")
    version: str = Field(description="版本号")
    tags: list[str] = Field(default_factory=list, description="标签")
    content: str = Field(description="提示词内容")
    variables: dict = Field(default_factory=dict, description="变量定义")
    extends: list[str] = Field(default_factory=list, description="继承的模板")
    image_config: Optional[dict] = Field(default=None, description="图片配置")
    created_at: Optional[str] = Field(description="创建时间")
    updated_at: Optional[str] = Field(description="更新时间")

    model_config = ConfigDict(from_attributes=True)


class UserPromptListItem(BaseModel):
    """提示词列表项（简化版）"""
    id: int = Field(description="提示词 ID")
    key: str = Field(description="模板 key")
    full_key: str = Field(description="完整 key")
    name: str = Field(description="显示名称")
    description: str = Field(description="描述")
    category: str = Field(description="分类")
    tags: list[str] = Field(default_factory=list, description="标签")
    is_public: bool = Field(description="是否公开")
    user_id: Optional[int] = Field(description="创建者 ID")
    created_at: Optional[str] = Field(description="创建时间")

    model_config = ConfigDict(from_attributes=True)


class UserPromptListResponse(BaseModel):
    """提示词列表响应"""
    prompts: list[UserPromptListItem] = Field(description="提示词列表")
    total: int = Field(description="总数")


class UserPromptCreateResponse(BaseModel):
    """创建提示词响应"""
    id: int = Field(description="提示词 ID")
    key: str = Field(description="模板 key")
    full_key: str = Field(description="完整 key（带前缀）")
    name: str = Field(description="显示名称")
    category: str = Field(description="分类")
    created_at: str = Field(description="创建时间")
