"""总结 Schema

定义内容总结相关的请求和响应模型。
"""
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.common import AIMetadata


class SummaryRequest(BaseModel):
    """总结请求"""
    text: Optional[str] = Field(
        default=None,
        description="要总结的文本内容",
        max_length=50000,
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="要总结的会话 ID"
    )
    style: Literal["brief", "detailed", "bullet"] = Field(
        default="brief",
        description="总结风格：brief=简洁, detailed=详细, bullet=要点"
    )
    max_length: Optional[int] = Field(
        default=None,
        ge=50,
        le=2000,
        description="总结最大长度"
    )
    language: str = Field(
        default="zh",
        description="输出语言：zh=中文, en=英文"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "这是一篇很长的文章,包含了很多内容...",
                "style": "bullet",
                "max_length": 500,
                "language": "zh",
            }
        }
    )


class SummaryResponse(BaseModel):
    """总结响应"""
    summary: str = Field(
        description="总结内容"
    )
    key_points: Optional[list[str]] = Field(
        default=None,
        description="关键要点（bullet 风格时返回）"
    )
    word_count: int = Field(
        description="总结字数"
    )
    compression_ratio: Optional[float] = Field(
        default=None,
        description="压缩比例（原文/总结）"
    )
    metadata: AIMetadata = Field(
        description="响应元数据"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "summary": "本文主要讨论了人工智能在医疗领域的应用...",
                "key_points": [
                    "AI 可以辅助医生诊断疾病",
                    "机器学习在药物研发中发挥重要作用",
                    "AI 医疗面临数据隐私挑战",
                ],
                "word_count": 150,
                "compression_ratio": 0.1,
                "metadata": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                },
            }
        }
    )


class ConversationSummaryRequest(BaseModel):
    """会话总结请求"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    style: Literal["brief", "detailed", "bullet"] = Field(
        default="brief",
        description="总结风格"
    )


class ConversationSummaryResponse(BaseModel):
    """会话总结响应"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    summary: str = Field(
        description="会话总结"
    )
    topics: list[str] = Field(
        default=[],
        description="讨论的主题"
    )
    message_count: int = Field(
        description="消息数量"
    )
    metadata: AIMetadata = Field(
        description="响应元数据"
    )
