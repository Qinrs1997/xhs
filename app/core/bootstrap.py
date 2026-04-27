"""应用启动时的初始化逻辑 (统一异步版)"""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import verify_password_async, get_password_hash_async
from app.crud import user as user_crud, role as role_crud
from app.schemas.user import UserCreate
from app.schemas.role import RoleCreate
from app.core.logger import logger


async def ensure_admin(db: AsyncSession) -> None:
    """确保存在初始管理员角色与账号 (异步幂等版)"""
    # 1) 确保 admin 角色存在
    admin_role = await role_crud.get_by_name(db, name="admin")
    if not admin_role:
        admin_role = await role_crud.create(
            db,
            obj_in=RoleCreate(
                name="admin",
                description="系统管理员",
                is_active=True,
            ),
        )

    # 2) 确保管理员账号存在
    admin_user = await user_crud.get_by_username(db, username=settings.BOOTSTRAP_ADMIN_USERNAME)

    if not admin_user:
        admin_user = await user_crud.get_by_email(db, email=settings.BOOTSTRAP_ADMIN_EMAIL)

    if not admin_user:
        if not settings.BOOTSTRAP_ADMIN_PASSWORD:
            logger.error("BOOTSTRAP_ADMIN_PASSWORD 未设置，跳过管理员创建")
            return
        try:
            admin_user = await user_crud.create(
                db,
                obj_in=UserCreate(
                    username=settings.BOOTSTRAP_ADMIN_USERNAME,
                    email=settings.BOOTSTRAP_ADMIN_EMAIL,
                    password=settings.BOOTSTRAP_ADMIN_PASSWORD,
                    full_name=settings.BOOTSTRAP_ADMIN_FULL_NAME,
                ),
            )
        except IntegrityError:
            await db.rollback()
            admin_user = await user_crud.get_by_email(db, email=settings.BOOTSTRAP_ADMIN_EMAIL)

    if not admin_user:
         logger.error("Failed to create or get admin user")
         return

    # 确保用户名一致
    if admin_user.username != settings.BOOTSTRAP_ADMIN_USERNAME:
        admin_user.username = settings.BOOTSTRAP_ADMIN_USERNAME
        db.add(admin_user)
        # 不立即 commit，后面统一处理

    changed = False
    if settings.BOOTSTRAP_ADMIN_PASSWORD and not await verify_password_async(settings.BOOTSTRAP_ADMIN_PASSWORD, admin_user.hashed_password):
        admin_user.hashed_password = await get_password_hash_async(settings.BOOTSTRAP_ADMIN_PASSWORD)
        changed = True
    if not admin_user.is_superuser:
        admin_user.is_superuser = True
        changed = True
    if not admin_user.is_active:
        admin_user.is_active = True
        changed = True

    if changed:
        db.add(admin_user)
        await db.commit()
        await db.refresh(admin_user)

    # 3) 关联 admin 角色
    await role_crud.assign_to_user(db, user_id=admin_user.id, role_id=admin_role.id)
    await db.commit()


async def ensure_ai_provider_async() -> None:
    """确认默认 AI 服务商配置 (优化版)"""
    from app.core.database import AsyncSessionLocal
    from app.models.ai import AIProvider

    try:
        from app.ai.config import ai_config

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AIProvider))
            existing = result.scalars().first()

            if existing:
                return

            default_provider = AIProvider(
                name="硅基流动 (DeepSeek)",
                provider_type="openai",
                api_key=ai_config.openai.api_key,
                base_url=ai_config.openai.base_url,
                default_model=ai_config.openai.chat_model,
                available_models={"models": ai_config.openai.available_models or [
                    "Pro/moonshotai/Kimi-K2.6",
                    "Pro/zai-org/GLM-5.1",
                    "Pro/MiniMaxAI/MiniMax-M2.5",
                    "deepseek-ai/DeepSeek-V3.2",
                    "deepseek-ai/DeepSeek-R1"
                ]},
                timeout=ai_config.openai.timeout,
                max_retries=ai_config.openai.max_retries,
                max_tokens=ai_config.openai.default_max_tokens,
                is_active=True,
                is_default=True,
                priority=100,
                description="系统默认 AI 服务商"
            )

            session.add(default_provider)
            await session.commit()
            logger.info("Default AI provider config created")
    except Exception as e:
        logger.warning("初始化 AI 服务商失败 (可能表未同步): {}", e)
