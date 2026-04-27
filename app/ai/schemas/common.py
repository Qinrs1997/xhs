"""通用 Schema

定义 AI 模块共用的数据模型。
"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """消息模型"""
    role: Literal["system", "user", "assistant"] = Field(
        description="消息角色"
    )
    content: str = Field(
        description="消息内容"
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="消息时间戳"
    )
    tokens: Optional[int] = Field(
        default=None,
        description="Token 数量"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "role": "user",
                "content": "你好,请介绍一下自己",
                "timestamp": "2024-01-01T12:00:00",
                "tokens": 15,
            }
        }
    )


class Usage(BaseModel):
    """Token 使用量"""
    prompt_tokens: int = Field(
        description="输入 Token 数"
    )
    completion_tokens: int = Field(
        description="输出 Token 数"
    )
    total_tokens: int = Field(
        description="总 Token 数"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prompt_tokens": 50,
                "completion_tokens": 100,
                "total_tokens": 150,
            }
        }
    )


class AIMetadata(BaseModel):
    """AI 响应元数据"""
    model: str = Field(
        description="使用的模型"
    )
    provider: str = Field(
        default="openai",
        description="服务商"
    )
    usage: Optional[Usage] = Field(
        default=None,
        description="Token 使用量"
    )
    latency_ms: Optional[int] = Field(
        default=None,
        description="响应延迟（毫秒）"
    )
    request_id: Optional[str] = Field(
        default=None,
        description="请求 ID"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "model": "gpt-4o-mini",
                "provider": "openai",
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 100,
                    "total_tokens": 150,
                },
                "latency_ms": 1500,
                "request_id": "req_abc123",
            }
        }
    )
