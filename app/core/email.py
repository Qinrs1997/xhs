"""邮件服务模块

提供异步邮件发送能力，支持：
- HTML + 纯文本邮件
- 内置邮件模板（密码重置、欢迎注册、系统通知）
- QQ邮箱 / 163邮箱 / 企业邮箱 SMTP

使用方法：
    from app.core.email import email_service

    # 发送密码重置邮件
    await email_service.send_password_reset_email(
        to_email="user@example.com",
        username="张三",
        reset_url="https://example.com/reset?token=xxx"
    )

    # 发送通用邮件
    await email_service.send_email(
        to_email="user@example.com",
        subject="测试邮件",
        html_content="<h1>你好</h1>"
    )
"""
import ssl
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import Optional
from datetime import datetime

from app.core.config import settings
from app.core.logger import logger


class EmailService:
    """
    异步邮件发送服务

    使用 smtplib（通过线程池异步化），兼容性最好，无需额外依赖。
    """

    def __init__(self):
        self.smtp_host: str = settings.EMAIL_SMTP_HOST
        self.smtp_port: int = settings.EMAIL_SMTP_PORT
        self.use_tls: bool = settings.EMAIL_SMTP_TLS
        self.from_email: str = settings.EMAIL_FROM
        self.from_name: str = settings.EMAIL_FROM_NAME
        self.password: str = settings.EMAIL_PASSWORD
        self.enabled: bool = settings.EMAIL_ENABLED

    @property
    def is_configured(self) -> bool:
        """检查邮件服务是否已正确配置"""
        return bool(self.enabled and self.from_email and self.password)

    def _send_sync(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> None:
        """
        同步发送邮件（内部方法，通过线程池调用）

        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            html_content: HTML 内容
            text_content: 纯文本内容（作为 HTML 的降级版本）
        """
        # 构建邮件
        msg = MIMEMultipart("alternative")
        # From 头：中文名需要 RFC2047 编码，否则 QQ 邮箱拒收
        from email.utils import formataddr
        msg["From"] = formataddr((str(Header(self.from_name, "utf-8")), self.from_email))
        msg["To"] = to_email
        msg["Subject"] = Header(subject, "utf-8")

        # 纯文本版本（兜底）
        if text_content:
            msg.attach(MIMEText(text_content, "plain", "utf-8"))

        # HTML 版本（优先显示）
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # 发送
        if self.use_tls:
            # SSL 直连（端口 465）
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=10) as server:
                server.login(self.from_email, self.password)
                server.sendmail(self.from_email, [to_email], msg.as_string())
        else:
            # STARTTLS（端口 587）
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.from_email, self.password)
                server.sendmail(self.from_email, [to_email], msg.as_string())

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """
        异步发送邮件

        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            html_content: HTML 内容
            text_content: 纯文本降级内容

        Returns:
            是否发送成功
        """
        if not self.is_configured:
            logger.warning("邮件服务未配置，跳过发送")
            return False

        try:
            # 将同步 SMTP 操作放到线程池，避免阻塞事件循环
            await asyncio.to_thread(
                self._send_sync,
                to_email, subject, html_content, text_content
            )
            logger.info("邮件发送成功: to={}, subject={}", to_email, subject)
            return True
        except Exception as e:
            logger.error("邮件发送失败: to={}, error={}", to_email, e)
            return False

    # ==================== 内置模板邮件 ====================

    async def send_password_reset_email(
        self,
        to_email: str,
        username: str,
        reset_url: str,
    ) -> bool:
        """
        发送密码重置邮件

        Args:
            to_email: 收件人邮箱
            username: 用户名
            reset_url: 重置链接（含 token）
        """
        subject = f"【{settings.PROJECT_NAME}】密码重置"
        html = self._render_template(
            "password_reset",
            username=username,
            reset_url=reset_url,
            project_name=settings.PROJECT_NAME,
            expire_minutes=15,
        )
        text = f"您好 {username}，请点击以下链接重置密码（15分钟内有效）：\n{reset_url}"
        return await self.send_email(to_email, subject, html, text)

    async def send_welcome_email(
        self,
        to_email: str,
        username: str,
    ) -> bool:
        """
        发送欢迎注册邮件

        Args:
            to_email: 收件人邮箱
            username: 用户名
        """
        subject = f"欢迎加入 {settings.PROJECT_NAME}"
        html = self._render_template(
            "welcome",
            username=username,
            project_name=settings.PROJECT_NAME,
            login_url=f"{settings.PROJECT_NAME}",
        )
        text = f"欢迎 {username} 加入 {settings.PROJECT_NAME}！"
        return await self.send_email(to_email, subject, html, text)

    async def send_notification_email(
        self,
        to_email: str,
        username: str,
        title: str,
        content: str,
    ) -> bool:
        """
        发送系统通知邮件

        Args:
            to_email: 收件人邮箱
            username: 用户名
            title: 通知标题
            content: 通知内容（支持 HTML）
        """
        subject = f"【{settings.PROJECT_NAME}】{title}"
        html = self._render_template(
            "notification",
            username=username,
            title=title,
            content=content,
            project_name=settings.PROJECT_NAME,
        )
        text = f"{username} 你好，系统通知：{title}\n{content}"
        return await self.send_email(to_email, subject, html, text)

    # ==================== 模板渲染 ====================

    def _render_template(self, template_name: str, **kwargs) -> str:
        """
        渲染邮件 HTML 模板

        使用简单的字符串替换，不引入额外模板引擎依赖。
        """
        templates = {
            "password_reset": self._template_password_reset,
            "welcome": self._template_welcome,
            "notification": self._template_notification,
        }

        template_func = templates.get(template_name)
        if not template_func:
            raise ValueError(f"未知的邮件模板: {template_name}")

        return template_func(**kwargs)

    @staticmethod
    def _base_template(body_content: str, project_name: str = "挽梦图文生成") -> str:
        """
        基础 HTML 邮件模板

        现代简约风格，兼容主流邮件客户端。
        """
        year = datetime.now().year
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7; padding:40px 20px;">
        <tr>
            <td align="center">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,0.08); overflow:hidden;">
                    <!-- 头部 -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding:32px 40px; text-align:center;">
                            <h1 style="color:#ffffff; margin:0; font-size:24px; font-weight:600; letter-spacing:1px;">
                                {project_name}
                            </h1>
                        </td>
                    </tr>
                    <!-- 内容 -->
                    <tr>
                        <td style="padding:40px;">
                            {body_content}
                        </td>
                    </tr>
                    <!-- 底部 -->
                    <tr>
                        <td style="background-color:#f8f9fa; padding:20px 40px; text-align:center; border-top:1px solid #e9ecef;">
                            <p style="color:#999; font-size:12px; margin:0; line-height:1.8;">
                                此邮件由系统自动发送，请勿直接回复<br>
                                © {year} {project_name} · All Rights Reserved
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

    def _template_password_reset(
        self,
        username: str,
        reset_url: str,
        project_name: str,
        expire_minutes: int = 15,
    ) -> str:
        """密码重置邮件模板"""
        body = f"""
            <h2 style="color:#333; margin:0 0 20px; font-size:20px;">密码重置</h2>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 10px;">
                您好，<strong>{username}</strong>
            </p>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 24px;">
                我们收到了您的密码重置请求。请点击下方按钮设置新密码：
            </p>
            <div style="text-align:center; margin:32px 0;">
                <a href="{reset_url}"
                   style="display:inline-block; padding:14px 48px; background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                          color:#ffffff; text-decoration:none; border-radius:8px; font-size:16px; font-weight:600;
                          box-shadow:0 4px 12px rgba(102,126,234,0.4);">
                    重置密码
                </a>
            </div>
            <div style="background-color:#fff8e1; border-left:4px solid #ffc107; padding:12px 16px; border-radius:4px; margin:24px 0;">
                <p style="color:#856404; font-size:13px; margin:0;">
                    ⏰ 此链接将在 <strong>{expire_minutes} 分钟</strong>后过期<br>
                    🔒 如果这不是您本人的操作，请忽略此邮件
                </p>
            </div>
            <p style="color:#999; font-size:13px; margin:24px 0 0;">
                如果按钮无法点击，请复制以下链接到浏览器：<br>
                <a href="{reset_url}" style="color:#667eea; word-break:break-all;">{reset_url}</a>
            </p>
        """
        return self._base_template(body, project_name)

    def _template_welcome(
        self,
        username: str,
        project_name: str,
        login_url: str = "",
    ) -> str:
        """欢迎注册邮件模板"""
        body = f"""
            <h2 style="color:#333; margin:0 0 20px; font-size:20px;">🎉 欢迎加入</h2>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 10px;">
                您好，<strong>{username}</strong>
            </p>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 24px;">
                感谢您注册 <strong>{project_name}</strong>！您的账户已创建成功。
            </p>
            <div style="background-color:#e8f5e9; border-radius:8px; padding:20px; margin:24px 0;">
                <p style="color:#2e7d32; font-size:14px; margin:0; line-height:1.8;">
                    ✅ 账户状态：<strong>已激活</strong><br>
                    👤 用户名：<strong>{username}</strong>
                </p>
            </div>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 10px;">
                如有任何问题，请联系系统管理员。
            </p>
        """
        return self._base_template(body, project_name)

    def _template_notification(
        self,
        username: str,
        title: str,
        content: str,
        project_name: str,
    ) -> str:
        """系统通知邮件模板"""
        body = f"""
            <h2 style="color:#333; margin:0 0 20px; font-size:20px;">📢 {title}</h2>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 10px;">
                您好，<strong>{username}</strong>
            </p>
            <div style="background-color:#f8f9fa; border-radius:8px; padding:20px; margin:16px 0 24px;">
                <div style="color:#333; font-size:14px; line-height:1.8;">
                    {content}
                </div>
            </div>
        """
        return self._base_template(body, project_name)

    def _template_verify_code(
        self,
        code: str,
        expire_minutes: int,
        project_name: str,
    ) -> str:
        """验证码邮件模板"""
        body = f"""
            <h2 style="color:#333; margin:0 0 20px; font-size:20px;">📧 邮箱验证码</h2>
            <p style="color:#555; font-size:15px; line-height:1.8; margin:0 0 10px;">
                您正在进行邮箱验证，验证码如下：
            </p>
            <div style="text-align:center; margin:24px 0;">
                <span style="display:inline-block; font-size:36px; font-weight:bold; letter-spacing:8px;
                       color:#1a73e8; background:#f0f4ff; border-radius:8px; padding:16px 32px;
                       border:2px dashed #1a73e8;">
                    {code}
                </span>
            </div>
            <p style="color:#555; font-size:14px; line-height:1.8; margin:0 0 10px;">
                验证码 <strong>{expire_minutes} 分钟</strong>内有效，请勿泄露给他人。
            </p>
            <p style="color:#999; font-size:13px; margin:16px 0 0;">
                如果这不是您本人的操作，请忽略此邮件。
            </p>
        """
        return self._base_template(body, project_name)

    async def send_verification_code_email(
        self,
        to_email: str,
        code: str,
        expire_minutes: int = 5,
    ) -> bool:
        """
        发送验证码邮件

        Args:
            to_email: 收件人邮箱
            code: 验证码
            expire_minutes: 有效期（分钟）

        Returns:
            是否发送成功
        """
        subject = f"【{settings.PROJECT_NAME}】邮箱验证码: {code}"
        html = self._template_verify_code(
            code=code,
            expire_minutes=expire_minutes,
            project_name=settings.PROJECT_NAME,
        )
        text = f"您的验证码是: {code}，{expire_minutes} 分钟内有效。"
        return await self.send_email(to_email, subject, html, text)


# 全局邮件服务实例
email_service = EmailService()
