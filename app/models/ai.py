from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
import uuid

from app.models.base import Base

class AIPrompt(Base):
    """提示词模板表"""
    __tablename__ = "ai_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), default="system", index=True) # system / user
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    key: Mapped[str] = mapped_column(String(100), index=True) # 模板标识, 如 chat/default
    name: Mapped[str] = mapped_column(String(100)) # 显示名称
    content: Mapped[str] = mapped_column(Text) # 提示词内容 (支持 Jinja2)
    variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True) # 变量定义

    version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False) # 针对用户创建的提示词是否公开
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class AIConversation(Base):
    """AI 会话主表"""
    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    model: Mapped[Optional[str]] = mapped_column(String(100)) # 使用的模型名称
    prompt_key: Mapped[Optional[str]] = mapped_column(String(100)) # 使用的提示词 Key

    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系映射
    messages = relationship("AIMessage", back_populates="conversation", cascade="all, delete-orphan")

class AIMessage(Base):
    """聊天记录详情表"""
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)

    role: Mapped[str] = mapped_column(String(20)) # user / assistant / system
    content: Mapped[str] = mapped_column(Text)

    token_count: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[Optional[str]] = mapped_column(String(100)) # 实际回答时的模型
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True) # 耗时、原始响应等

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)

    conversation = relationship("AIConversation", back_populates="messages")


class AIProvider(Base):
    """AI 服务商配置表 (支持管理员动态配置)"""
    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # 配置名称，如 "硅基流动", "OpenAI官方"
    provider_type: Mapped[str] = mapped_column(String(20), default="openai")  # openai / azure / nanbo / stability ...
    service_type: Mapped[str] = mapped_column(String(20), default="llm", index=True)  # llm / image / search

    # API 配置 (兼容 OpenAI 规范)
    api_key: Mapped[str] = mapped_column(String(255))  # 加密存储
    base_url: Mapped[str] = mapped_column(String(255))  # 如 https://api.siliconflow.cn/v1

    # 模型配置
    default_model: Mapped[str] = mapped_column(String(100), default="gpt-3.5-turbo")
    available_models: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 可用模型列表

    # 请求配置
    timeout: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否为默认服务商
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 优先级，用于故障切换

    # 备注
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 类型专属配置（图片尺寸/搜索深度等）
    extra_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AIUsageLog(Base):
    """AI 使用记录表 (用量统计)"""
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True)

    model: Mapped[str] = mapped_column(String(100))
    endpoint: Mapped[str] = mapped_column(String(50))  # chat / summary / search / image

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # 响应时间
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AISettings(Base):
    """AI 全局设置表 (管理员动态配置)"""
    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)  # 配置键名
    value: Mapped[str] = mapped_column(Text)  # 配置值 (JSON 字符串)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
