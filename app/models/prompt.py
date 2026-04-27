"""用户提示词模型

存储用户和管理员创建的自定义提示词。
使用 SQLAlchemy 2.0 Mapped 风格。
"""
from typing import Optional, List, Any
from sqlalchemy import String, Text, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import JSON

from app.models.base import BaseModel


class UserPrompt(BaseModel):
    """用户自定义提示词

    支持用户创建个人模板，管理员创建公共模板。

    Key 命名规范：
    - 用户模板使用时: user:{key} 或 user:{user_id}:{key}
    - 公共模板使用时: public:{key}
    - 系统模板保持: chat/default, roles/business/sales 等
    """
    __tablename__ = "user_prompts"

    # 唯一标识 key（同一用户下唯一）
    key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="模板 key，如 my_translator"
    )

    # 归属
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="创建者用户 ID，NULL 表示公共模板"
    )

    # 可见性
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
        comment="是否公开给所有用户"
    )

    # 元数据
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="显示名称"
    )
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        comment="描述说明"
    )
    category: Mapped[str] = mapped_column(
        String(50),
        default="custom",
        index=True,
        comment="分类: custom, chat, summary, search, image, role"
    )
    version: Mapped[str] = mapped_column(
        String(20),
        default="1.0.0",
        comment="版本号"
    )
    tags: Mapped[Optional[List]] = mapped_column(
        JSON,
        default=list,
        comment="标签数组"
    )

    # 内容
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="提示词内容，支持 {{variable}} 变量"
    )
    variables: Mapped[Optional[dict]] = mapped_column(
        JSON,
        default=dict,
        comment="变量定义，如 {name: {type: string, required: true}}"
    )
    extends: Mapped[Optional[List]] = mapped_column(
        JSON,
        default=list,
        comment="继承的模板 key 列表"
    )

    # 图片生成专用配置（可选）
    image_config: Mapped[Optional[dict]] = mapped_column(
        JSON,
        default=None,
        comment="图片生成配置，如 {model: dall-e-3, size: 1024x1024}"
    )

    # 关系（默认懒加载，代码只引用 prompt.user_id，未访问 prompt.user）
    user = relationship("User", backref="prompts")

    # 索引和约束
    __table_args__ = (
        # 同一用户下 key 唯一（允许不同用户使用相同 key）
        UniqueConstraint('user_id', 'key', name='uix_user_prompt_key'),
        {"comment": "用户提示词表"}
    )

    def __repr__(self) -> str:
        return f"<UserPrompt(id={self.id}, key='{self.key}', user_id={self.user_id})>"

    @property
    def full_key(self) -> str:
        """获取完整的模板 key（带前缀）"""
        if self.user_id:
            return f"user:{self.key}"
        else:
            return f"public:{self.key}"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "key": self.key,
            "full_key": self.full_key,
            "user_id": self.user_id,
            "is_public": self.is_public,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "tags": self.tags or [],
            "content": self.content,
            "variables": self.variables or {},
            "extends": self.extends or [],
            "image_config": self.image_config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
