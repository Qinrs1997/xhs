"""Token 计数器

用于估算消息的 token 数量，支持上下文窗口管理。

使用方式：
    from app.ai.core.token_counter import get_token_counter

    counter = get_token_counter()
    tokens = counter.count("Hello, world!")
    tokens = counter.count_messages([...])
"""
from typing import Optional
from functools import lru_cache

from app.core.logger import logger


class TokenCounter:
    """Token 计数器

    使用 tiktoken 进行精确计数（如果可用），
    否则使用简单的估算方法。
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        """
        初始化 Token 计数器

        Args:
            model: 模型名称，用于选择正确的编码器
        """
        self.model = model
        self._encoding = None
        self._use_tiktoken = False

        # 尝试加载 tiktoken
        try:
            import tiktoken
            self._encoding = tiktoken.encoding_for_model(model)
            self._use_tiktoken = True
            logger.debug("Token 计数器已初始化，使用 tiktoken 编码器: {}", model)
        except ImportError:
            logger.warning("tiktoken 未安装，使用估算方法计数 token")
        except Exception as e:
            logger.warning("无法加载 tiktoken 编码器: {}，使用估算方法", e)

    def count(self, text: str) -> int:
        """
        计算文本的 token 数量

        Args:
            text: 输入文本

        Returns:
            token 数量
        """
        if not text:
            return 0

        if self._use_tiktoken and self._encoding:
            return len(self._encoding.encode(text))

        # 简单估算：中文约 1.5 字符/token，英文约 4 字符/token
        # 混合内容取平均值约 2.5 字符/token
        return max(1, len(text) // 2)

    def count_messages(
        self,
        messages: list[dict],
        count_reply: bool = True
    ) -> int:
        """
        计算消息列表的 token 数量

        基于 OpenAI 的 token 计算规则：
        - 每条消息有固定开销（约 4 tokens）
        - role 和 content 分别计算
        - 回复消息有额外开销（约 3 tokens）

        Args:
            messages: 消息列表，每条消息包含 role 和 content
            count_reply: 是否计算回复开销

        Returns:
            总 token 数量
        """
        if not messages:
            return 0

        total_tokens = 0

        for message in messages:
            # 每条消息的固定开销
            total_tokens += 4

            # 计算 role
            role = message.get("role", "")
            total_tokens += self.count(role)

            # 计算 content
            content = message.get("content", "")
            if isinstance(content, str):
                total_tokens += self.count(content)
            elif isinstance(content, list):
                # 多模态消息
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total_tokens += self.count(item["text"])

        # 回复消息的固定开销
        if count_reply:
            total_tokens += 3

        return total_tokens

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        model: Optional[str] = None
    ) -> float:
        """
        估算 API 调用成本（USD）

        基于 OpenAI 2024 年定价：
        - gpt-4o: $2.50/1M input, $10.00/1M output
        - gpt-4o-mini: $0.15/1M input, $0.60/1M output
        - gpt-3.5-turbo: $0.50/1M input, $1.50/1M output

        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            model: 模型名称

        Returns:
            估算成本（USD）
        """
        model = model or self.model

        # 定价表 (input_per_1m, output_per_1m)
        pricing = {
            "gpt-4o": (2.50, 10.00),
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-3.5-turbo": (0.50, 1.50),
            "gpt-4-turbo": (10.00, 30.00),
            "gpt-4": (30.00, 60.00),
        }

        # 查找匹配的定价
        input_price, output_price = pricing.get(model, (0.15, 0.60))

        # 计算成本
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price

        return input_cost + output_cost


@lru_cache()
def get_token_counter(model: str = "gpt-4o-mini") -> TokenCounter:
    """获取 Token 计数器实例（缓存）"""
    return TokenCounter(model)
