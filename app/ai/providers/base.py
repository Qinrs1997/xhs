"""AI Provider 抽象基类

定义所有 AI 服务商必须实现的接口。

扩展新服务商时：
1. 创建新文件 (如 anthropic.py)
2. 继承 BaseProvider
3. 实现所有抽象方法
4. 在 __init__.py 中注册
"""
from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator, Any
from dataclasses import dataclass


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system, user, assistant
    content: str


@dataclass
class ChatResponse:
    """聊天响应"""
    content: str
    model: str
    usage: dict  # {prompt_tokens, completion_tokens, total_tokens}
    finish_reason: str
    raw_response: Optional[Any] = None  # 原始响应（调试用）


@dataclass
class ChatChunk:
    """流式聊天块"""
    content: str
    is_final: bool = False
    finish_reason: Optional[str] = None


@dataclass
class EmbeddingResponse:
    """嵌入向量响应"""
    embeddings: list[list[float]]
    model: str
    usage: dict


@dataclass
class ImageResponseItem:
    """单张图像数据"""
    url: Optional[str] = None
    b64_json: Optional[str] = None
    revised_prompt: Optional[str] = None


@dataclass
class ImageResponse:
    """图像生成响应（支持多图返回）"""
    url: Optional[str] = None
    b64_json: Optional[str] = None
    revised_prompt: Optional[str] = None
    model: str = ""
    # 多图返回
    images: list[ImageResponseItem] = None  # type: ignore[assignment]
    seed: Optional[int] = None
    inference_time_ms: Optional[int] = None

    def __post_init__(self):
        # 兼容旧代码：如果 images 为空，用单张数据构造
        if self.images is None:
            if self.url or self.b64_json:
                self.images = [ImageResponseItem(
                    url=self.url,
                    b64_json=self.b64_json,
                    revised_prompt=self.revised_prompt,
                )]
            else:
                self.images = []


class BaseProvider(ABC):
    """AI 服务商抽象基类

    所有 AI Provider 必须实现此接口。
    """

    # Provider 名称
    name: str = "base"

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> ChatResponse | AsyncIterator[ChatChunk]:
        """
        聊天补全

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称
            temperature: 采样温度 (0-2)
            max_tokens: 最大生成 token 数
            stream: 是否流式输出
            **kwargs: 其他模型特定参数

        Returns:
            普通模式: ChatResponse
            流式模式: AsyncIterator[ChatChunk]
        """
        pass

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncIterator[ChatChunk]:
        """
        流式聊天补全

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            **kwargs: 其他参数

        Yields:
            ChatChunk 流式块
        """
        pass

    async def embedding(
        self,
        text: str | list[str],
        model: Optional[str] = None,
    ) -> EmbeddingResponse:
        """
        文本嵌入向量化

        Args:
            text: 输入文本或文本列表
            model: 嵌入模型名称

        Returns:
            EmbeddingResponse
        """
        raise NotImplementedError("该 Provider 不支持 Embedding")

    async def image_generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        n: int = 1,
        negative_prompt: Optional[str] = None,
        image: Optional[str] = None,
        extra_params: Optional[dict] = None,
        **kwargs
    ) -> ImageResponse:
        """
        图像生成

        Args:
            prompt: 图像描述
            model: 图像模型名称
            size: 图像尺寸（WxH 格式，如 1024x1024）
            quality: 图像质量
            n: 生成数量
            negative_prompt: 反向提示词
            image: 参考图（base64 或 URL，用于图生图/编辑）
            extra_params: 透传给模型的额外参数
            **kwargs: 其他参数

        Returns:
            ImageResponse
        """
        raise NotImplementedError("该 Provider 不支持图像生成")

    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            服务是否可用
        """
        try:
            # 发送简单请求测试连接（返回值丢弃，只关心是否抛异常）
            await self.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
