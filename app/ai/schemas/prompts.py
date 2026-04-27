"""提示词管理 Schema

定义提示词管理相关的请求和响应模型。
统一展示系统模板（文件）和用户模板（数据库）。
"""
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class PromptInfo(BaseModel):
    """提示词信息（统一格式）"""
    id: Optional[int] = Field(default=None, description="数据库 ID（系统模板为 null）")
    key: str = Field(description="模板 key")
    name: str = Field(default="", description="显示名称")
    description: str = Field(default="", description="描述")
    category: str = Field(default="custom", description="分类: xhs, chat, custom 等")
    version: str = Field(default="1.0.0", description="版本号")
    tags: list[str] = Field(default_factory=list, description="标签")
    variables: list[str] = Field(default_factory=list, description="变量列表")
    source: str = Field(default="system", description="来源: system=内置, user=用户, public=公共")
    is_readonly: bool = Field(default=True, description="是否只读（系统模板为 true）")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class PromptListResponse(BaseModel):
    """提示词列表响应"""
    prompts: list[PromptInfo] = Field(description="提示词列表")
    total: int = Field(description="总数")


class PromptDetailResponse(BaseModel):
    """提示词详情响应"""
    id: Optional[int] = Field(default=None, description="数据库 ID")
    key: str = Field(description="模板 key")
    name: str = Field(default="", description="显示名称")
    version: str = Field(default="1.0.0", description="版本号")
    description: str = Field(default="", description="描述")
    author: str = Field(default="", description="作者")
    category: str = Field(default="custom", description="分类")
    extends: list[str] = Field(default_factory=list, description="继承的模板")
    variables: dict[str, Any] = Field(default_factory=dict, description="变量定义")
    tags: list[str] = Field(default_factory=list, description="标签")
    content_preview: str = Field(default="", description="内容预览（前500字符）")
    source: str = Field(default="system", description="来源")
    is_readonly: bool = Field(default=True, description="是否只读")


class PromptPreviewRequest(BaseModel):
    """提示词预览请求"""
    key: str = Field(description="模板 key")
    variables: Optional[dict] = Field(
        default=None,
        description="模板变量"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "xhs/content",
                "variables": {
                    "topic": "春季穿搭",
                    "style": "种草",
                },
            }
        }
    )


class PromptPreviewResponse(BaseModel):
    """提示词预览响应"""
    key: str = Field(description="模板 key")
    rendered_content: str = Field(description="渲染后的内容")
    variables_used: list[str] = Field(
        default_factory=list,
        description="使用的变量列表"
    )
    token_count: int = Field(
        default=0,
        description="预估 Token 数"
    )
