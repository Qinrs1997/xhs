"""异步认证 API

端点文件仅做路由绑定，业务逻辑在 services/auth_service.py
"""
from typing import Any
from fastapi import APIRouter, Depends, status, Body, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import (
    verify_token,
    verify_password_async, get_password_hash_async,
)
from app.core.exceptions import AuthenticationError, DuplicateError, BadRequestError, NotFoundError
from app.core.audit import get_audit_logger, AuditLogger, AuditAction
from app.core.logger import logger
from app.core.email import email_service
from app.core.token_blacklist import token_blacklist
from app.core.verify_code import verify_code_store
from app.api.deps import get_current_active_user, get_current_superuser, oauth2_scheme
from app.crud import user as user_crud
from app.schemas import Token, UserLogin, UserCreate, User, Response
from app.schemas.user import (
    UserRegister, SendVerifyCodeRequest,
    ChangePassword, AdminResetPassword,
    ForgotPasswordRequest, ResetPasswordConfirm,
    RefreshTokenRequest,
)
from app.services.auth_service import auth_service
from app.services.credit_service import credit_service

router = APIRouter()


# ==================== API 端点 ====================

@router.post(
    "/send-code",
    response_model=Response[dict],
    summary="发送邮箱验证码",
)
async def send_verify_code(
    request_in: SendVerifyCodeRequest,
    request: Request = None,
) -> Any:
    """
    发送邮箱验证码

    - 60 秒内不可重复发送
    - 同一 IP 每分钟最多 3 次
    - 验证码 5 分钟有效
    - 用于注册时的邮箱验证
    """
    # 获取客户端 IP
    client_ip = request.client.host if request and request.client else ""

    # 检查邮件服务
    if not email_service.is_configured:
        raise BadRequestError("邮件服务未配置，无法发送验证码")

    # 生成验证码（含 IP 限流）
    code, error = verify_code_store.generate(request_in.email, client_ip=client_ip)
    if error:
        raise BadRequestError(error)

    # 发送邮件
    sent = await email_service.send_verification_code_email(
        to_email=request_in.email,
        code=code,
        expire_minutes=5,
    )

    if not sent:
        raise BadRequestError("验证码发送失败，请稍后重试")

    return Response(
        code=200,
        success=True,
        message="验证码已发送",
        data={"email": request_in.email, "expire_minutes": 5}
    )


@router.post(
    "/register",
    response_model=Response[User],
    status_code=status.HTTP_200_OK,
    summary="用户注册"
)
async def register(
    *,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    user_in: UserRegister
) -> Any:
    """
    用户注册（需邮箱验证码）

    流程：
    1. 先调 POST /send-code 发送验证码到邮箱
    2. 用户填写验证码后调本接口完成注册
    3. 如带邀请码，双方均获得积分奖励
    """
    # 验证邮箱验证码
    ok, error = verify_code_store.verify(user_in.email, user_in.verify_code)
    if not ok:
        raise BadRequestError(error)

    # 检查用户名是否已存在
    user = await user_crud.get_by_username(db, username=user_in.username)
    if user:
        raise DuplicateError("用户名已存在")

    # 检查邮箱是否已存在
    user = await user_crud.get_by_email(db, email=user_in.email)
    if user:
        raise DuplicateError("邮箱已存在")

    # 创建用户（用 UserCreate 构造，去掉 verify_code）
    create_data = UserCreate(
        username=user_in.username,
        email=user_in.email,
        password=user_in.password,
        full_name=user_in.full_name,
        avatar=user_in.avatar,
    )
    user = await user_crud.create(db, obj_in=create_data)

    # 注册赠送积分 + 处理邀请码
    try:
        client_ip = request.client.host if request.client else None
        await credit_service.grant_register_bonus(db, user.id)
        if user_in.invite_code:
            await credit_service.process_invite_reward(
                db, user.id, user_in.invite_code, ip_address=client_ip
            )
        await db.commit()
    except Exception as credit_err:
        logger.warning("注册积分处理失败（不影响注册）: {}", credit_err)

    return Response(code=200, success=True, message="注册成功", data=user)


@router.post("/login", response_model=Response[Token], summary="用户登录")
async def login(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """用户登录（适配前端需求，表单格式）"""
    client_ip = request.client.host if request.client else ""
    result = await auth_service.login(
        db,
        username=form_data.username,
        password=form_data.password,
        client_ip=client_ip,
    )

    return Response(
        code=200,
        success=True,
        message="登录成功",
        data=auth_service.build_token_response(result)
    )


@router.post(
    "/login-token",
    response_model=Token,
    summary="用户登录（标准 OAuth2 响应，供 Swagger Authorize 使用）",
    include_in_schema=False,
)
async def login_token(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """为适配 Swagger 和前端，返回完整 Token 信息"""
    client_ip = request.client.host if request.client else ""
    result = await auth_service.login(
        db,
        username=form_data.username,
        password=form_data.password,
        client_ip=client_ip,
    )

    return auth_service.build_token_response(result)


@router.post("/login-json", response_model=Response[Token], summary="用户登录（JSON）")
async def login_json(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_in: UserLogin,
    request: Request,
) -> Any:
    """用户登录（JSON 格式，适配前端）"""
    client_ip = request.client.host if request.client else ""
    result = await auth_service.login(
        db,
        username=user_in.username,
        password=user_in.password,
        client_ip=client_ip,
    )

    return Response(
        code=200,
        success=True,
        message="登录成功",
        data=auth_service.build_token_response(result)
    )


@router.post("/refresh-token", response_model=Response[Token], summary="刷新 Token")
async def refresh_token(
    payload_in: RefreshTokenRequest,
    db: AsyncSession = Depends(get_async_db)
) -> Any:
    """刷新 Token（兼容 refreshToken / refresh_token 两种字段名）"""
    token = payload_in.refresh_token
    try:
        payload = verify_token(token)
        if payload.get("type") != "refresh":
            raise AuthenticationError("无效的刷新令牌")
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("无效的刷新令牌")
    except AuthenticationError:
        raise
    except (HTTPException, ValueError, KeyError):
        raise AuthenticationError("无效的刷新令牌") from None

    user = await user_crud.get(db, int(user_id))
    if not user or not user.is_active:
        raise AuthenticationError("用户不存在或已禁用")

    access_token, new_refresh_token, expires = auth_service.generate_tokens(int(user_id))
    roles, permissions = auth_service.get_user_permissions(user)

    await token_blacklist.add(token, payload)

    token_obj = Token(
        access_token=access_token,
        token_type="bearer",
        accessToken=access_token,
        refreshToken=new_refresh_token,
        expires=expires,
        username=user.username,
        nickname=user.full_name or user.username,
        avatar=user.avatar,
        roles=roles,
        permissions=permissions,
    )

    return Response(
        code=200,
        success=True,
        message="刷新成功",
        data=token_obj,
    )


# ==================== 密码修改/重置 ====================

@router.put("/change-password", response_model=Response[None], summary="修改密码")
async def change_password(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: Any = Depends(get_current_active_user),
    password_in: ChangePassword,
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_UPDATE,
        description="用户修改密码"
    ))
) -> Any:
    """
    修改当前用户密码

    - 需要验证旧密码
    - 新密码与确认密码必须一致
    - 新密码不能与旧密码相同
    """
    # 验证新密码与确认密码一致
    if password_in.new_password != password_in.confirm_password:
        raise BadRequestError("两次输入的新密码不一致")

    # 验证旧密码是否正确
    if not await verify_password_async(password_in.old_password, current_user.hashed_password):
        await audit.log(success=False, error_message="旧密码验证失败")
        raise AuthenticationError("旧密码错误")

    # 新密码不能与旧密码相同
    if await verify_password_async(password_in.new_password, current_user.hashed_password):
        raise BadRequestError("新密码不能与旧密码相同")

    # 更新密码
    current_user.hashed_password = await get_password_hash_async(password_in.new_password)
    db.add(current_user)
    await db.commit()

    # 撤销该用户所有旧 Token（密码已改，旧 session 必须失效）
    await token_blacklist.revoke_user(current_user.id)

    await audit.log(detail={"action": "change_password"})

    return Response(code=200, success=True, message="密码修改成功，请重新登录")


@router.put(
    "/admin/reset-password/{user_id}",
    response_model=Response[None],
    summary="管理员重置用户密码"
)
async def admin_reset_password(
    *,
    db: AsyncSession = Depends(get_async_db),
    user_id: int,
    password_in: AdminResetPassword,
    current_user: Any = Depends(get_current_superuser),
    audit: AuditLogger = Depends(get_audit_logger(
        action=AuditAction.USER_UPDATE,
        description="管理员重置用户密码"
    ))
) -> Any:
    """
    管理员重置指定用户密码（仅超级用户）

    - 不需要验证旧密码
    - 直接设置新密码
    """
    target_user = await user_crud.get(db, id=user_id)
    if not target_user:
        raise NotFoundError("用户不存在")

    # 更新密码
    target_user.hashed_password = await get_password_hash_async(password_in.new_password)
    db.add(target_user)
    await db.commit()

    # 撤销目标用户所有旧 Token
    await token_blacklist.revoke_user(user_id)

    await audit.log(detail={
        "target_user_id": user_id,
        "target_username": target_user.username,
    })

    return Response(code=200, success=True, message=f"用户 {target_user.username} 的密码已重置，其所有登录已失效")


@router.post("/forgot-password", response_model=Response[None], summary="忘记密码 - 发送验证码")
async def forgot_password(
    *,
    db: AsyncSession = Depends(get_async_db),
    request_in: ForgotPasswordRequest,
    request: Request = None,
) -> Any:
    """
    忘记密码 - 发送验证码到邮箱

    流程：
    1. 输入注册邮箱
    2. 系统发送 6 位验证码到邮箱（5 分钟有效）
    3. 用户拿到验证码后调 POST /reset-password 设置新密码

    ⚠️ 安全说明：无论邮箱是否存在，都返回成功，防止邮箱枚举攻击
    """
    client_ip = request.client.host if request and request.client else ""
    result = {"message": "如果该邮箱已注册，将收到密码重置验证码"}

    user = await user_crud.get_by_email(db, email=request_in.email)

    if user and user.is_active:
        if not email_service.is_configured:
            raise BadRequestError("邮件服务未配置")

        # 生成验证码（含 IP 限流）
        code, error = verify_code_store.generate(request_in.email, client_ip=client_ip)
        if error:
            raise BadRequestError(error)

        # 发送验证码邮件
        sent = await email_service.send_verification_code_email(
            to_email=request_in.email,
            code=code,
            expire_minutes=5,
        )
        if sent:
            logger.info("密码重置验证码已发送: user_id={}, email={}", user.id, user.email)
        else:
            logger.warning("密码重置验证码发送失败: email={}", request_in.email)
            raise BadRequestError("验证码发送失败，请稍后重试")

    return Response(code=200, success=True, message="操作成功", data=result)


@router.post("/reset-password", response_model=Response[None], summary="重置密码")
async def reset_password(
    *,
    db: AsyncSession = Depends(get_async_db),
    reset_in: ResetPasswordConfirm,
) -> Any:
    """
    忘记密码 - 确认重置（通过邮箱验证码）

    流程：
    1. 先调 POST /forgot-password 发送验证码
    2. 用户输入验证码 + 新密码调本接口
    """
    # 验证新密码与确认密码一致
    if reset_in.new_password != reset_in.confirm_password:
        raise BadRequestError("两次输入的新密码不一致")

    # 验证邮箱验证码
    ok, error = verify_code_store.verify(reset_in.email, reset_in.verify_code)
    if not ok:
        raise BadRequestError(error)

    # 查找用户
    user = await user_crud.get_by_email(db, email=reset_in.email)
    if not user:
        raise BadRequestError("邮箱未注册")

    if not user.is_active:
        raise BadRequestError("用户已被禁用，无法重置密码")

    # 更新密码
    user.hashed_password = await get_password_hash_async(reset_in.new_password)
    db.add(user)
    await db.commit()

    # 撤销该用户所有旧 Token
    await token_blacklist.revoke_user(user.id)

    logger.info("用户 {} 通过验证码重置了密码", user.username)

    return Response(code=200, success=True, message="密码重置成功，请使用新密码登录")


# ==================== 登出 ====================

@router.post("/logout", response_model=Response, summary="登出")
async def logout(
    token: str = Depends(oauth2_scheme),
):
    """
    登出当前用户

    将当前 Token 加入黑名单，使其立即失效。
    前端应同时清除本地存储的 Token。
    """
    try:
        # 解码 token 获取 payload（即使验证失败也要加入黑名单）
        payload = verify_token(token)
        await token_blacklist.add(token, payload)
    except Exception:
        # 即使 token 已过期，也标记为黑名单（防止时钟偏差）
        await token_blacklist.add(token, {"exp": 0})

    return Response(code=200, success=True, message="登出成功")

