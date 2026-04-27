"""提示词 CRUD 操作

提供用户提示词的增删改查功能。
"""
from typing import Optional
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import UserPrompt
from app.core.logger import logger


class PromptCRUD:
    """提示词 CRUD 操作类"""

    # ==================== 创建 ====================

    async def create(
        self,
        db: AsyncSession,
        *,
        key: str,
        name: str,
        content: str,
        user_id: Optional[int] = None,
        description: str = "",
        category: str = "custom",
        variables: Optional[dict] = None,
        extends: Optional[list] = None,
        tags: Optional[list] = None,
        is_public: bool = False,
        image_config: Optional[dict] = None,
        commit: bool = True,
    ) -> UserPrompt:
        """
        创建提示词

        Args:
            db: 数据库会话
            key: 模板 key
            name: 显示名称
            content: 提示词内容
            user_id: 用户 ID（None 表示公共模板）
            description: 描述
            category: 分类
            variables: 变量定义
            extends: 继承的模板
            tags: 标签
            is_public: 是否公开
            image_config: 图片配置
            commit: 是否自动提交

        Returns:
            创建的 UserPrompt 对象
        """
        prompt = UserPrompt(
            key=key,
            name=name,
            content=content,
            user_id=user_id,
            description=description,
            category=category,
            variables=variables or {},
            extends=extends or [],
            tags=tags or [],
            is_public=is_public,
            image_config=image_config,
        )

        db.add(prompt)

        if commit:
            await db.commit()
            await db.refresh(prompt)

        logger.info("创建提示词: key={}, user_id={}", key, user_id)
        return prompt

    # ==================== 查询 ====================

    async def get_by_id(
        self,
        db: AsyncSession,
        prompt_id: int,
    ) -> Optional[UserPrompt]:
        """根据 ID 获取提示词"""
        result = await db.execute(
            select(UserPrompt).where(UserPrompt.id == prompt_id)
        )
        return result.scalar_one_or_none()

    async def get_by_key(
        self,
        db: AsyncSession,
        key: str,
        user_id: Optional[int] = None,
    ) -> Optional[UserPrompt]:
        """
        根据 key 获取提示词

        查找优先级：
        1. 用户自己的模板
        2. 公共模板
        """
        # 先查用户自己的
        if user_id:
            result = await db.execute(
                select(UserPrompt).where(
                    and_(
                        UserPrompt.key == key,
                        UserPrompt.user_id == user_id,
                    )
                )
            )
            prompt = result.scalar_one_or_none()
            if prompt:
                return prompt

        # 再查公共的
        result = await db.execute(
            select(UserPrompt).where(
                and_(
                    UserPrompt.key == key,
                    or_(
                        UserPrompt.user_id.is_(None),
                        UserPrompt.is_public.is_(True),
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_user_prompts(
        self,
        db: AsyncSession,
        user_id: int,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserPrompt]:
        """
        获取用户的提示词列表

        Args:
            db: 数据库会话
            user_id: 用户 ID
            category: 分类过滤
            skip: 跳过数量
            limit: 返回数量限制

        Returns:
            用户的提示词列表
        """
        query = select(UserPrompt).where(UserPrompt.user_id == user_id)

        if category:
            query = query.where(UserPrompt.category == category)

        query = query.order_by(UserPrompt.updated_at.desc())
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_public_prompts(
        self,
        db: AsyncSession,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserPrompt]:
        """获取公共提示词列表"""
        query = select(UserPrompt).where(
            or_(
                UserPrompt.user_id.is_(None),
                UserPrompt.is_public.is_(True),
            )
        )

        if category:
            query = query.where(UserPrompt.category == category)

        query = query.order_by(UserPrompt.updated_at.desc())
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_available_prompts(
        self,
        db: AsyncSession,
        user_id: int,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserPrompt]:
        """
        获取用户可用的所有提示词（自己的 + 公共的）
        """
        query = select(UserPrompt).where(
            or_(
                UserPrompt.user_id == user_id,
                UserPrompt.user_id.is_(None),
                UserPrompt.is_public.is_(True),
            )
        )

        if category:
            query = query.where(UserPrompt.category == category)

        query = query.order_by(UserPrompt.updated_at.desc())
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_all_prompts(
        self,
        db: AsyncSession,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UserPrompt]:
        """获取所有提示词（管理员用）"""
        query = select(UserPrompt)

        if category:
            query = query.where(UserPrompt.category == category)

        query = query.order_by(UserPrompt.updated_at.desc())
        query = query.offset(skip).limit(limit)

        result = await db.execute(query)
        return list(result.scalars().all())

    async def count_user_prompts(
        self,
        db: AsyncSession,
        user_id: int,
    ) -> int:
        """统计用户的提示词数量"""
        from sqlalchemy import func
        result = await db.execute(
            select(func.count(UserPrompt.id)).where(UserPrompt.user_id == user_id)
        )
        return result.scalar() or 0

    # ==================== 更新 ====================

    async def update(
        self,
        db: AsyncSession,
        prompt: UserPrompt,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        category: Optional[str] = None,
        variables: Optional[dict] = None,
        extends: Optional[list] = None,
        tags: Optional[list] = None,
        is_public: Optional[bool] = None,
        image_config: Optional[dict] = None,
        commit: bool = True,
    ) -> UserPrompt:
        """更新提示词"""
        if name is not None:
            prompt.name = name
        if description is not None:
            prompt.description = description
        if content is not None:
            prompt.content = content
        if category is not None:
            prompt.category = category
        if variables is not None:
            prompt.variables = variables
        if extends is not None:
            prompt.extends = extends
        if tags is not None:
            prompt.tags = tags
        if is_public is not None:
            prompt.is_public = is_public
        if image_config is not None:
            prompt.image_config = image_config

        if commit:
            await db.commit()
            await db.refresh(prompt)

        logger.info("更新提示词: id={}, key={}", prompt.id, prompt.key)
        return prompt

    # ==================== 删除 ====================

    async def delete(
        self,
        db: AsyncSession,
        prompt: UserPrompt,
        commit: bool = True,
    ) -> bool:
        """删除提示词"""
        prompt_id = prompt.id
        prompt_key = prompt.key

        await db.delete(prompt)

        if commit:
            await db.commit()

        logger.info("删除提示词: id={}, key={}", prompt_id, prompt_key)
        return True

    # ==================== 校验 ====================

    async def key_exists(
        self,
        db: AsyncSession,
        key: str,
        user_id: Optional[int] = None,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """检查 key 是否已存在"""
        query = select(UserPrompt.id).where(UserPrompt.key == key)

        if user_id is not None:
            query = query.where(UserPrompt.user_id == user_id)
        else:
            query = query.where(UserPrompt.user_id.is_(None))

        if exclude_id:
            query = query.where(UserPrompt.id != exclude_id)

        result = await db.execute(query)
        return result.scalar_one_or_none() is not None

    async def can_access(
        self,
        db: AsyncSession,
        prompt_id: int,
        user_id: int,
        is_admin: bool = False,
    ) -> bool:
        """检查用户是否有权访问该提示词"""
        prompt = await self.get_by_id(db, prompt_id)
        if not prompt:
            return False

        # 管理员可以访问所有
        if is_admin:
            return True

        # 用户可以访问自己的
        if prompt.user_id == user_id:
            return True

        # 可以访问公共的
        if prompt.user_id is None or prompt.is_public:
            return True

        return False

    async def can_modify(
        self,
        db: AsyncSession,
        prompt_id: int,
        user_id: int,
        is_admin: bool = False,
    ) -> bool:
        """检查用户是否有权修改该提示词"""
        prompt = await self.get_by_id(db, prompt_id)
        if not prompt:
            return False

        # 管理员可以修改所有
        if is_admin:
            return True

        # 用户只能修改自己的
        return prompt.user_id == user_id


# 全局实例
prompt_crud = PromptCRUD()
