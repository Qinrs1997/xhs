"""聊天 Schema

定义聊天相关的请求和响应模型。
"""
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.common import Message, AIMetadata


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(
        description="用户消息内容",
        min_length=1,
        max_length=10000,
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="会话 ID，为空则创建新会话"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="系统提示词（优先级高于 prompt_key）",
        max_length=5000,
    )
    prompt_key: Optional[str] = Field(
        default=None,
        description="提示词模板 key，如 'chat/default', 'roles/business/customer_service'"
    )
    prompt_variables: Optional[dict] = Field(
        default=None,
        description="提示词模板变量，如 {'company_name': 'ABC科技'}"
    )
    model: Optional[str] = Field(
        default=None,
        description="指定模型，默认使用配置的模型"
    )
    temperature: float = Field(
        default=0.7,
        ge=0,
        le=2,
        description="采样温度，越高越随机"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        le=32000,
        description="最大生成 Token 数"
    )
    stream: bool = Field(
        default=False,
        description="是否流式输出"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "你好,请帮我写一首关于春天的诗",
                "conversation_id": None,
                "system_prompt": None,
                "prompt_key": "chat/default",
                "prompt_variables": None,
                "temperature": 0.8,
                "stream": False,
            }
        }
    )


class ChatResponse(BaseModel):
    """聊天响应"""
    content: str = Field(
        description="助手回复内容"
    )
    conversation_id: str = Field(
        description="会话 ID"
    )
    metadata: AIMetadata = Field(
        description="响应元数据"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "春风拂柳绿丝绦,\n暖阳融融照山腰。\n桃花笑迎蝴蝶舞,\n燕子归来把巢找。",
                "conversation_id": "conv_abc123",
                "metadata": {
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 50,
                        "total_tokens": 80,
                    },
                    "latency_ms": 1200,
                },
            }
        }
    )


class ChatChunk(BaseModel):
    """流式聊天块"""
    content: str = Field(
        description="内容片段"
    )
    is_final: bool = Field(
        default=False,
        description="是否是最后一块"
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="会话 ID（仅最后一块包含）"
    )
    metadata: Optional[AIMetadata] = Field(
        default=None,
        description="元数据（仅最后一块包含）"
    )


class ChatStreamResponse(BaseModel):
    """流式聊天响应（SSE 格式说明）"""
    event: Literal["message", "done", "error"] = Field(
        description="事件类型"
    )
    data: ChatChunk = Field(
        description="数据块"
    )


class ChatHistoryRequest(BaseModel):
    """获取聊天历史请求"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="返回消息数量限制"
    )


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    messages: list[Message] = Field(
        description="消息历史"
    )
    total_tokens: int = Field(
        description="总 Token 数"
    )


class CreateConversationRequest(BaseModel):
    """创建会话请求"""
    prompt_key: Optional[str] = Field(
        default=None,
        description="提示词模板 key，如 'roles/business/customer_service'"
    )
    prompt_variables: Optional[dict] = Field(
        default=None,
        description="提示词模板变量"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="自定义系统提示词（优先级高于 prompt_key）"
    )
    title: Optional[str] = Field(
        default=None,
        description="会话标题"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="自定义元数据"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prompt_key": "roles/business/customer_service",
                "prompt_variables": {"company_name": "ABC科技"},
                "title": "客服咨询",
            }
        }
    )


class CreateConversationResponse(BaseModel):
    """创建会话响应"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    created_at: str = Field(
        description="创建时间"
    )
    prompt_key: Optional[str] = Field(
        default=None,
        description="使用的提示词模板"
    )
    system_prompt_preview: Optional[str] = Field(
        default=None,
        description="系统提示词预览（前200字符）"
    )


class ConversationDetailResponse(BaseModel):
    """会话详情响应"""
    conversation_id: str = Field(
        description="会话 ID"
    )
    created_at: Optional[str] = Field(
        default=None,
        description="创建时间"
    )
    updated_at: Optional[str] = Field(
        default=None,
        description="最后更新时间"
    )
    prompt_key: Optional[str] = Field(
        default=None,
        description="使用的提示词模板"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="系统提示词"
    )
    message_count: int = Field(
        default=0,
        description="消息数量"
    )
    total_tokens: int = Field(
        default=0,
        description="总 Token 数"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="自定义元数据"
    )

