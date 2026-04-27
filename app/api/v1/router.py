"""API v1 路由"""
from fastapi import APIRouter

from app.api.v1.endpoints import users, auth, roles, audit_logs, announcements, uploads, departments, scheduler, user_preferences, credits, payment

api_router = APIRouter()

# ==================== 核心路由（始终注册） ====================
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])
api_router.include_router(user_preferences.router, prefix="/user", tags=["用户偏好设置"])
api_router.include_router(roles.router, prefix="/roles", tags=["角色管理"])
api_router.include_router(departments.router, prefix="/departments", tags=["部门管理"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["审计日志"])
api_router.include_router(announcements.router, prefix="/announcements", tags=["公告管理"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["上传接口"])
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["定时任务管理"])
# credits.router 无 prefix：子模块已拆分（credits_user/membership/invite/admin），
# 仍通过 credits.py 聚合挂载以保持 /credits/*, /membership/*, /invite/*, /admin/* 路径兼容
api_router.include_router(credits.router, tags=["积分与会员"])
api_router.include_router(payment.router, tags=["支付"])

# ==================== 可选模块（根据配置注册） ====================

# 邮件模块：根据 email.enabled 配置决定是否注册
try:
    from app.core.config import settings as _settings
    if _settings.EMAIL_ENABLED:
        from app.api.v1.endpoints import email
        api_router.include_router(email.router, prefix="/email", tags=["邮件服务"])
except ImportError:
    pass

# AI 模块：根据 ai.enabled 配置决定是否注册
try:
    from app.ai.config import ai_config
    if ai_config.enabled:
        from app.api.v1.endpoints import ai, prompts, ai_admin
        api_router.include_router(ai.router, prefix="/ai", tags=["AI 服务"])
        api_router.include_router(prompts.router, prefix="/ai/prompts", tags=["AI 提示词管理"])
        api_router.include_router(ai_admin.router, prefix="/admin/ai", tags=["AI 管理 (管理员)"])

        # XHS 任务管理（独立于 xhs_enabled，任务保存功能始终可用）
        from app.api.v1.endpoints import xhs_tasks
        api_router.include_router(xhs_tasks.router, prefix="/xhs", tags=["XHS 任务管理"])

        # XHS 模板（始终可用）
        from app.api.v1.endpoints import xhs_templates
        api_router.include_router(xhs_templates.router, prefix="/xhs/templates", tags=["XHS 模板"])

        # XHS 模板管理端 CRUD（仅超管）
        from app.api.v1.endpoints import xhs_templates_admin
        api_router.include_router(
            xhs_templates_admin.router,
            prefix="/admin/xhs/templates",
            tags=["XHS 模板 (管理员)"]
        )

        if ai_config.xhs_enabled:
            from app.api.v1.endpoints import xhs
            # XHS 生成接口已拆分为 xhs_generate + xhs_batch，通过 xhs.py 聚合
            # 与 xhs_tasks（/tasks/*）共享 /xhs 前缀，无路径冲突
            api_router.include_router(xhs.router, prefix="/xhs", tags=["小红书图文生成"])
except ImportError:
    # AI 模块未安装或配置错误，跳过
    pass

