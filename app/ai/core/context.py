"""上下文管理器 (持久化增强版)

管理会话历史、上下文窗口控制、系统 Prompt 等。
支持内存与数据库持久化。
"""
import uuid
from datetime import datetime
from typing import Optional, Literal
from dataclasses import dataclass, field

from app.ai.config import ai_config
from app.ai.core.token_counter import get_token_counter
from app.core.logger import logger
from app.core.timezone import now_utc

@dataclass
class Message:
    """单条消息"""
    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: datetime = field(default_factory=now_utc)
    tokens: int = 0
    model: Optional[str] = None

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

    def to_full_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "tokens": self.tokens,
            "model": self.model
        }

@dataclass
class ConversationContext:
    """会话上下文"""
    conversation_id: str
    user_id: Optional[int] = None
    system_prompt: Optional[str] = None
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    is_summarized: bool = False

    def __post_init__(self):
        self._token_counter = get_token_counter()
        if not self.messages:
            self._recalculate_tokens()

    def _recalculate_tokens(self) -> None:
        total = 0
        if self.system_prompt:
            total += self._token_counter.count(self.system_prompt) + 4
        for msg in self.messages:
            if msg.tokens == 0:
                msg.tokens = self._token_counter.count(msg.content) + 4
            total += msg.tokens
        self.total_tokens = total

    def add_message(self, role: str, content: str, model: str | None = None) -> Message:
        tokens = self._token_counter.count(content) + 4
        message = Message(role=role, content=content, tokens=tokens, model=model)
        self.messages.append(message)
        self.total_tokens += tokens
        self.updated_at = now_utc()
        return message

    def add_user_message(self, content: str) -> Message:
        """添加用户消息"""
        return self.add_message("user", content)

    def add_assistant_message(self, content: str, model: str | None = None) -> Message:
        """添加助手消息"""
        return self.add_message("assistant", content, model=model)

    def set_system_prompt(self, prompt: str) -> None:
        """设置系统提示词"""
        old_tokens = 0
        if self.system_prompt:
            old_tokens = self._token_counter.count(self.system_prompt) + 4
        self.system_prompt = prompt
        new_tokens = self._token_counter.count(prompt) + 4
        self.total_tokens = self.total_tokens - old_tokens + new_tokens
        self.updated_at = now_utc()

    def clear(self) -> None:
        """清空消息历史"""
        self.messages = []
        self.total_tokens = 0
        if self.system_prompt:
            self.total_tokens = self._token_counter.count(self.system_prompt) + 4
        self.updated_at = now_utc()

    def get_history(self, limit: int | None = None) -> list[dict]:
        """获取消息历史"""
        messages = self.messages[-limit:] if limit else self.messages
        return [msg.to_full_dict() for msg in messages]

    def get_messages_for_api(self, max_tokens: int | None = None, include_system: bool = True) -> list[dict]:
        max_tokens = max_tokens or ai_config.context.max_tokens
        result = []
        current_tokens = 0

        if include_system and self.system_prompt:
            system_tokens = self._token_counter.count(self.system_prompt) + 4
            result.append({"role": "system", "content": self.system_prompt})
            current_tokens += system_tokens

        available_tokens = max_tokens - current_tokens - 800
        selected_messages = []
        for msg in reversed(self.messages):
            if current_tokens + msg.tokens <= available_tokens:
                selected_messages.insert(0, msg.to_dict())
                current_tokens += msg.tokens
            else:
                break
        result.extend(selected_messages)
        return result

class ContextManager:
    """上下文管理器 (支持 DB 持久化)"""

    def __init__(self):
        self._contexts: dict[str, ConversationContext] = {}
        self._storage_type = ai_config.context.storage_type
        # 即使配置是 memory，如果有数据库模块，我们也支持 save 落地
        logger.info("上下文管理器已就绪，主要存储: {}", self._storage_type)

    async def get_or_create(
        self,
        conversation_id: str | None = None,
        user_id: int | None = None,
        system_prompt: str | None = None,
    ) -> ConversationContext:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # 1. 尝试从内存获取
        if conversation_id in self._contexts:
            ctx = self._contexts[conversation_id]
            if system_prompt and system_prompt != ctx.system_prompt:
                ctx.system_prompt = system_prompt
                ctx._recalculate_tokens()
            return ctx

        # 2. 尝试从数据库恢复历史
        db_ctx = await self._load_from_db(conversation_id)
        if db_ctx:
            # 存入内存缓存
            self._contexts[conversation_id] = db_ctx
            if system_prompt: db_ctx.system_prompt = system_prompt
            return db_ctx

        # 3. 创建新会话
        ctx = ConversationContext(
            conversation_id=conversation_id,
            user_id=user_id,
            system_prompt=system_prompt,
        )
        self._contexts[conversation_id] = ctx
        return ctx

    async def save(self, context: ConversationContext) -> None:
        """持久化保存会话历史到数据库"""
        self._contexts[context.conversation_id] = context

        # 内部服务调用（如 XHS 生成）不带 user_id，跳过数据库持久化
        if context.user_id is None:
            return

        try:
            from app.core.database import AsyncSessionLocal
            from app.models.ai import AIConversation, AIMessage
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                # 1. 检查会话是否存在
                stmt = select(AIConversation).where(AIConversation.id == context.conversation_id)
                result = await session.execute(stmt)
                db_conv = result.scalar_one_or_none()

                if not db_conv:
                    db_conv = AIConversation(
                        id=context.conversation_id,
                        user_id=context.user_id,
                        title=context.messages[0].content[:50] if context.messages else "新对话",
                        prompt_key=context.system_prompt[:50] if context.system_prompt else None
                    )
                    session.add(db_conv)

                db_conv.total_tokens = context.total_tokens
                db_conv.updated_at = now_utc()

                # 2. 同步消息记录 (此处采用简单增量：对比消息数量)
                # 实际生产建议采用更严谨的 LAST_MSG_ID 对比
                stmt_msg = select(AIMessage).where(AIMessage.conversation_id == context.conversation_id)
                msg_count_res = await session.execute(stmt_msg)
                db_msg_count = len(msg_count_res.scalars().all())

                if len(context.messages) > db_msg_count:
                    # 插入新消息
                    new_msgs = context.messages[db_msg_count:]
                    for msg in new_msgs:
                        session.add(AIMessage(
                            conversation_id=context.conversation_id,
                            role=msg.role,
                            content=msg.content,
                            token_count=msg.tokens,
                            model=msg.model,
                            created_at=msg.timestamp
                        ))

                await session.commit()
                # logger.debug("会话 {} 持久化成功", context.conversation_id)
        except Exception as e:
            logger.error("持久化会话失败: {}", e)

    async def get(self, conversation_id: str) -> Optional[ConversationContext]:
        """获取会话上下文（优先内存，其次数据库）"""
        # 1. 尝试从内存获取
        if conversation_id in self._contexts:
            return self._contexts[conversation_id]

        # 2. 尝试从数据库加载
        db_ctx = await self._load_from_db(conversation_id)
        if db_ctx:
            self._contexts[conversation_id] = db_ctx
            return db_ctx

        return None

    async def _load_from_db(self, conversation_id: str) -> Optional[ConversationContext]:
        """从数据库恢复会话对象"""
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.ai import AIConversation, AIMessage
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                conv_stmt = select(AIConversation).where(AIConversation.id == conversation_id)
                conv_res = await session.execute(conv_stmt)
                db_conv = conv_res.scalar_one_or_none()

                if not db_conv: return None

                msg_stmt = select(AIMessage).where(AIMessage.conversation_id == conversation_id).order_by(AIMessage.id)
                msg_res = await session.execute(msg_stmt)
                db_msgs = msg_res.scalars().all()

                messages = [
                    Message(
                        role=m.role,
                        content=m.content,
                        timestamp=m.created_at,
                        tokens=m.token_count or 0,
                        model=m.model
                    ) for m in db_msgs
                ]

                ctx = ConversationContext(
                    conversation_id=db_conv.id,
                    user_id=db_conv.user_id,
                    messages=messages,
                    created_at=db_conv.created_at,
                    updated_at=db_conv.updated_at,
                    total_tokens=db_conv.total_tokens
                )
                return ctx
        except Exception as e:
            logger.warning("从数据库恢复会话失败 {}: {}", conversation_id, e)
            return None

    async def delete(self, conversation_id: str) -> bool:
        if conversation_id in self._contexts:
            del self._contexts[conversation_id]

        # 级联删除数据库中的记录
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.ai import AIConversation
            from sqlalchemy import delete
            async with AsyncSessionLocal() as session:
                await session.execute(delete(AIConversation).where(AIConversation.id == conversation_id))
                await session.commit()
            return True
        except Exception:
            return False

    async def list_user_conversations(self, user_id: int, limit: int = 20) -> list[dict]:
        """从数据库获取用户会话列表"""
        try:
            from app.core.database import AsyncSessionLocal
            from app.models.ai import AIConversation
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                stmt = select(AIConversation).where(AIConversation.user_id == user_id).order_by(AIConversation.updated_at.desc()).limit(limit)
                result = await session.execute(stmt)
                db_convs = result.scalars().all()
                return [
                    {
                        "conversation_id": c.id,
                        "title": c.title,
                        "created_at": c.created_at.isoformat(),
                        "updated_at": c.updated_at.isoformat(),
                        "total_tokens": c.total_tokens
                    } for c in db_convs
                ]
        except Exception:
            return []

    def get_stats(self) -> dict:
        return {"active_in_memory": len(self._contexts), "storage_type": "hybrid_db"}

_context_manager = None

def get_context_manager() -> ContextManager:
    global _context_manager
    if _context_manager is None:
        _context_manager = ContextManager()
    return _context_manager
