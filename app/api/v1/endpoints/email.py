"""邮件服务 API

提供邮件发送和服务状态查询接口。
路由前缀: /api/v1/email
"""
from typing import Any
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends

from app.core.email import email_service
from app.api.deps import get_current_superuser
from app.models.user import User as UserModel
from app.schemas.response import Response


# ==================== 请求/响应 Schema ====================

class SendEmailRequest(BaseModel):
    """发送邮件请求"""
    to_email: EmailStr = Field(..., description="收件人邮箱")
    subject: str = Field(..., min_length=1, max_length=200, description="邮件主题")
    content: str = Field(..., min_length=1, description="邮件内容（支持 HTML）")


class SendNotificationRequest(BaseModel):
    """发送通知邮件请求"""
    to_email: EmailStr = Field(..., description="收件人邮箱")
    username: str = Field(..., description="收件人用户名")
    title: str = Field(..., min_length=1, max_length=200, description="通知标题")
    content: str = Field(..., min_length=1, description="通知内容（支持 HTML）")


class SendTestEmailRequest(BaseModel):
    """发送测试邮件请求"""
    to_email: EmailStr = Field(..., description="测试收件人邮箱")


class EmailStatusResponse(BaseModel):
    """邮件服务状态"""
    enabled: bool = Field(..., description="是否启用")
    configured: bool = Field(..., description="是否已配置")
    smtp_host: str = Field(..., description="SMTP 服务器")
    smtp_port: int = Field(..., description="SMTP 端口")
    from_email: str = Field(..., description="发件人邮箱（脱敏）")


# ==================== 路由 ====================

router = APIRouter()


@router.get(
    "/status",
    response_model=Response[EmailStatusResponse],
    summary="邮件服务状态",
)
async def get_email_status(
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """获取邮件服务配置状态（仅管理员）"""
    # 邮箱脱敏
    from_email = email_service.from_email
    if from_email and "@" in from_email:
        local, domain = from_email.split("@", 1)
        masked = local[:2] + "***" if len(local) > 2 else local + "***"
        from_email = f"{masked}@{domain}"

    return Response(
        code=200,
        success=True,
        message="ok",
        data=EmailStatusResponse(
            enabled=email_service.enabled,
            configured=email_service.is_configured,
            smtp_host=email_service.smtp_host,
            smtp_port=email_service.smtp_port,
            from_email=from_email,
        )
    )


@router.post(
    "/send/test",
    response_model=Response[dict],
    summary="发送测试邮件",
)
async def send_test_email(
    *,
    request_in: SendTestEmailRequest,
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """发送测试邮件，验证 SMTP 配置是否正确（仅管理员）"""
    if not email_service.is_configured:
        return Response(code=400, success=False, message="邮件服务未配置，请检查 EMAIL_FROM 和 EMAIL_PASSWORD 环境变量")

    success = await email_service.send_notification_email(
        to_email=request_in.to_email,
        username="管理员",
        title="SMTP 测试邮件",
        content="<p>如果您看到这封邮件，说明邮件服务配置成功！</p><p>此邮件由系统测试自动发送。</p>",
    )

    if success:
        return Response(code=200, success=True, message="测试邮件发送成功", data={"to": request_in.to_email})
    else:
        return Response(code=500, success=False, message="邮件发送失败，请检查 SMTP 配置和网络")


@router.post(
    "/send/notification",
    response_model=Response[dict],
    summary="发送通知邮件",
)
async def send_notification(
    *,
    request_in: SendNotificationRequest,
    current_user: UserModel = Depends(get_current_superuser),
) -> Any:
    """发送系统通知邮件（仅管理员）"""
    if not email_service.is_configured:
        return Response(code=400, success=False, message="邮件服务未配置")

    success = await email_service.send_notification_email(
        to_email=request_in.to_email,
        username=request_in.username,
        title=request_in.title,
        content=request_in.content,
    )

    if success:
        return Response(code=200, success=True, message="通知邮件发送成功", data={"to": request_in.to_email})
    else:
        return Response(code=500, success=False, message="邮件发送失败")
