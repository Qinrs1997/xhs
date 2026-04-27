"""用户偏好设置 API

提供菜单偏好的获取、更新、重置接口。
路由前缀: /api/v1/user
"""
from typing import Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.api.deps import get_current_active_user
from app.models.user import User as UserModel
from app.schemas.response import Response
from app.schemas.user import MenuPreferencesUpdate, MenuPreferencesResponse
from app.core.logger import logger

router = APIRouter()


@router.get(
    "/menu-preferences",
    response_model=Response[MenuPreferencesResponse],
    summary="获取菜单偏好设置",
    description="获取当前用户隐藏的菜单列表"
)
async def get_menu_preferences(
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> Any:
    """获取当前用户的菜单偏好设置"""
    prefs = current_user.menu_preferences or {}

    return Response(
        code=200,
        success=True,
        message="ok",
        data=MenuPreferencesResponse(
            hidden_menus=prefs.get("hidden_menus", []),
            updated_at=prefs.get("updated_at")
        )
    )


@router.put(
    "/menu-preferences",
    response_model=Response[MenuPreferencesResponse],
    summary="更新菜单偏好设置",
    description="保存用户隐藏的菜单路径列表"
)
async def update_menu_preferences(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_active_user),
    prefs_in: MenuPreferencesUpdate,
) -> Any:
    """更新当前用户的菜单偏好设置"""
    now = datetime.now(timezone.utc).isoformat()

    # 去重并排序，保持一致性
    hidden_menus = sorted(set(prefs_in.hidden_menus))

    # 构造存储数据
    menu_prefs = {
        "hidden_menus": hidden_menus,
        "updated_at": now,
    }

    # 直接更新 JSON 字段
    current_user.menu_preferences = menu_prefs
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    logger.info("用户 {} 更新菜单偏好: 隐藏 {} 个菜单", current_user.username, len(hidden_menus))

    return Response(
        code=200,
        success=True,
        message="菜单偏好已更新",
        data=MenuPreferencesResponse(
            hidden_menus=hidden_menus,
            updated_at=now
        )
    )


@router.delete(
    "/menu-preferences",
    response_model=Response[MenuPreferencesResponse],
    summary="重置菜单偏好",
    description="恢复默认菜单设置（清空隐藏列表）"
)
async def reset_menu_preferences(
    db: AsyncSession = Depends(get_async_db),
    current_user: UserModel = Depends(get_current_active_user),
) -> Any:
    """重置当前用户的菜单偏好（恢复默认）"""
    now = datetime.now(timezone.utc).isoformat()

    # 清空偏好
    current_user.menu_preferences = {
        "hidden_menus": [],
        "updated_at": now,
    }
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    logger.info("用户 {} 重置菜单偏好", current_user.username)

    return Response(
        code=200,
        success=True,
        message="菜单偏好已重置",
        data=MenuPreferencesResponse(
            hidden_menus=[],
            updated_at=now
        )
    )
