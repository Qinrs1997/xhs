"""AI Provider 层

提供多服务商的抽象接口，支持：
- LiteLLM（默认，统一调用 100+ 模型）
- OpenAI（直接调用，备选）

使用方式：
    from app.ai.providers import get_provider

    provider = get_provider("litellm")  # 默认
    response = await provider.chat_completion(messages)

LiteLLM 支持的模型命名：
    - OpenAI:      "openai/gpt-4o"
    - Claude:      "anthropic/claude-3-5-sonnet"
    - Gemini:      "gemini/gemini-2.0-flash"
    - 通义千问:     "dashscope/qwen-max"
    - 自定义兼容:   直接用模型名（自动加 openai/ 前缀）
"""
from app.ai.providers.base import BaseProvider
from app.ai.providers.litellm_provider import LiteLLMProvider
from app.ai.providers.openai import OpenAIProvider


def get_provider(provider_name: str = "openai") -> BaseProvider:
    """
    获取 AI Provider 实例

    Args:
        provider_name: 服务商名称
            - "openai": 使用 LiteLLM 统一调用（默认，兼容旧配置名）
            - "litellm": 同上，显式指定 LiteLLM
            - "openai_direct": 直接使用 OpenAI SDK（备选）

    Returns:
        Provider 实例

    Raises:
        ValueError: 不支持的服务商
    """
    providers = {
        "openai": LiteLLMProvider,          # 默认用 LiteLLM（兼容旧配置）
        "litellm": LiteLLMProvider,         # 显式指定 LiteLLM
        "openai_direct": OpenAIProvider,    # 原始 OpenAI SDK（备选）
    }

    if provider_name not in providers:
        raise ValueError(f"不支持的 AI 服务商: {provider_name}，可选: {list(providers.keys())}")

    return providers[provider_name]()


__all__ = [
    "BaseProvider",
    "LiteLLMProvider",
    "OpenAIProvider",
    "get_provider",
]

