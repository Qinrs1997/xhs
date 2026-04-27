"""AI 管理相关 Schema

定义 AI 服务商管理和全局配置相关的请求/响应模式。
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


# ==================== 全局配置 ====================

# 默认全局 AI 配置
DEFAULT_AI_GLOBAL_CONFIG = {
    "enabled": True,                    # AI 总开关（关闭后前端不显示 AI 界面）
    "chat_enabled": True,               # 聊天功能
    "summary_enabled": True,            # 总结功能
    "search_enabled": False,            # 联网搜索
    "image_enabled": False,             # 图像生成
    "data_analysis_enabled": False,     # 数据分析
    "max_tokens_per_request": 4096,     # 单次请求最大 Token
    "max_requests_per_day": 100,        # 每日最大请求数（0=无限制）
    "allowed_models": [],               # 允许使用的模型列表（空=全部允许）
}


class AIGlobalConfigUpdate(BaseModel):
    """更新全局 AI 配置"""
    enabled: Optional[bool] = Field(None, description="AI 总开关")
    chat_enabled: Optional[bool] = Field(None, description="聊天功能开关")
    summary_enabled: Optional[bool] = Field(None, description="总结功能开关")
    search_enabled: Optional[bool] = Field(None, description="联网搜索开关")
    image_enabled: Optional[bool] = Field(None, description="图像生成开关")
    data_analysis_enabled: Optional[bool] = Field(None, description="数据分析开关")
    max_tokens_per_request: Optional[int] = Field(None, description="单次最大Token")
    max_requests_per_day: Optional[int] = Field(None, description="每日最大请求数")
    allowed_models: Optional[List[str]] = Field(None, description="允许的模型列表")


class AIGlobalConfigResponse(BaseModel):
    """全局 AI 配置响应"""
    config: dict = Field(..., description="配置内容")
    source: str = Field(..., description="配置来源: database/default")


# ==================== 服务商管理 ====================

class AIProviderCreate(BaseModel):
    """创建 AI 服务商"""
    name: str = Field(..., description="配置名称，如 硅基流动")
    provider_type: str = Field(default="openai", description="类型: openai/azure/nanbo/stability/tavily...")
    service_type: str = Field(default="llm", description="服务类型: llm/image/search")
    api_key: str = Field(..., description="API 密钥")
    base_url: str = Field(..., description="API 地址，如 https://api.siliconflow.cn/v1")
    default_model: str = Field(default="gpt-3.5-turbo", description="默认模型")
    available_models: Optional[List[str]] = Field(default=None, description="可用模型列表")
    timeout: int = Field(default=60, description="请求超时(秒)")
    max_retries: int = Field(default=3, description="重试次数")
    max_tokens: int = Field(default=4096, description="默认最大Token")
    priority: int = Field(default=0, description="优先级")
    is_active: bool = Field(default=True, description="是否启用")
    is_default: bool = Field(default=False, description="是否设为默认")
    description: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = Field(default=None, description="类型专属配置（图片尺寸/搜索深度等）")


class AIProviderUpdate(BaseModel):
    """更新 AI 服务商"""
    name: Optional[str] = None
    provider_type: Optional[str] = None
    service_type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    available_models: Optional[List[str]] = None
    timeout: Optional[int] = None
    max_retries: Optional[int] = None
    max_tokens: Optional[int] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    priority: Optional[int] = None
    description: Optional[str] = None
    extra_config: Optional[Dict[str, Any]] = None


class AIProviderResponse(BaseModel):
    """AI 服务商响应"""
    id: int
    name: str
    provider_type: str
    service_type: str = "llm"
    base_url: str
    default_model: str
    available_models: Optional[List[str]]
    timeout: int
    max_retries: int
    max_tokens: int
    is_active: bool
    is_default: bool
    priority: int
    description: Optional[str]
    # 注意：不返回 api_key，保护敏感信息
    api_key_preview: str = Field(..., description="API 密钥预览（仅显示前4位和后4位）")
    extra_config: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== 用量统计 ====================

class UsageStatsResponse(BaseModel):
    """用量统计响应"""
    total_requests: int = Field(..., description="总请求数")
    total_tokens: int = Field(..., description="总 Token 数")
    total_prompt_tokens: int = Field(..., description="输入 Token 数")
    total_completion_tokens: int = Field(..., description="输出 Token 数")
    success_rate: float = Field(..., description="成功率")
    avg_latency_ms: float = Field(..., description="平均延迟(毫秒)")


class UsageByModelResponse(BaseModel):
    """按模型分组的用量统计"""
    model: str = Field(..., description="模型名称")
    request_count: int = Field(..., description="请求次数")
    total_tokens: int = Field(..., description="总 Token 数")


# ==================== 通用响应 ====================

class MessageResponse(BaseModel):
    """通用消息响应"""
    message: str = Field(..., description="消息内容")


class ReloadConfigResponse(BaseModel):
    """重载配置响应"""
    message: str = Field(..., description="消息")
    current_config: dict = Field(..., description="当前配置")


class ProviderTestResponse(BaseModel):
    """服务商测试响应"""
    status: str = Field(..., description="状态: success/error")
    provider: str = Field(..., description="服务商名称")
    latency_ms: int = Field(..., description="延迟(毫秒)")
    model_count: Optional[int] = Field(None, description="可用模型数量")
    error: Optional[str] = Field(None, description="错误信息")
