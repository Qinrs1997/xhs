"""邀请相关接口

- GET  /invite/code       获取邀请码和链接
- GET  /invite/stats      邀请统计
- GET  /invite/list       邀请明细列表
- GET  /invite/validate   验证邀请码
"""
from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.response import Response
from app.schemas.credit import InviteStatsResponse, InviteCodeResponse, InviteListResponse, InviteValidateResponse
from app.services.credit_service import credit_service

router = APIRouter()


@router.get("/invite/code", response_model=Response[InviteCodeResponse],
            summary="获取邀请码和链接")
async def get_invite_code(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    from app.core.config import settings

    code = await credit_service.ensure_invite_code(db, current_user.id)
    await db.commit()

    base_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
    invite_link = f"{base_url}/register?invite={code}"

    return Response(code=200, success=True, message="获取成功", data={
        "invite_code": code,
        "invite_link": invite_link,
        "reward_rules": {
            "inviter_reward": 100,
            "invitee_reward": 20,
            "daily_limit": 10,
        },
    })


@router.get("/invite/stats", response_model=Response[InviteStatsResponse],
            summary="邀请统计")
async def get_invite_stats(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    data = await credit_service.get_invite_stats(db, current_user.id)
    return Response(code=200, success=True, message="查询成功", data=data)


@router.get("/invite/list", response_model=Response[InviteListResponse],
            summary="邀请明细列表")
async def get_invite_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    data = await credit_service.get_invite_list(
        db, current_user.id, page=page, page_size=page_size
    )
    return Response(code=200, success=True, message="查询成功", data=data)


@router.get("/invite/validate", response_model=Response[InviteValidateResponse],
            summary="验证邀请码")
async def validate_invite_code(
    code: str = Query(..., description="邀请码"),
    db: AsyncSession = Depends(get_async_db),
) -> Any:
    inviter = await db.scalar(
        select(User).where(User.invite_code == code)
    )
    if not inviter:
        return Response(code=200, success=True, message="查询成功", data={
            "valid": False,
            "message": "邀请码无效",
        })

    return Response(code=200, success=True, message="查询成功", data={
        "valid": True,
        "inviter_name": inviter.username,
        "reward": 20,
        "message": f"来自 {inviter.username} 的邀请，注册后双方均获积分奖励",
    })
