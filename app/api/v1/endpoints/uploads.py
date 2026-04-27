"""通用文件上传接口"""
from typing import Any
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.storage import storage
from app.core.exceptions import ValidationError
from app.core.config import settings
from app.schemas.response import Response
from app.models.user import User

router = APIRouter()

_MAX_SIZE_MB = settings.MAX_UPLOAD_SIZE / (1024 * 1024)


@router.post("", response_model=Response[dict], summary="普通文件上传")
async def upload_file(
    file: UploadFile = File(..., description=f"文件大小限制 {_MAX_SIZE_MB:.0f}MB"),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """上传文件到通用目录

    - 仅允许登录用户上传
    - 支持格式：jpg, jpeg, png, gif, webp
    - 包含 MIME 魔数校验，防止恶意文件伪装
    """
    if not file.filename:
        raise ValidationError("文件名不能为空")
    file_url = await storage.save(file, sub_dir="others")
    return Response(
        code=200,
        success=True,
        message="上传成功",
        data={"url": file_url}
    )

@router.post("/avatar", response_model=Response[dict], summary="用户头像上传")
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(deps.get_async_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """上传并更新用户头像

    - 仅支持图片格式
    - 上传后自动更新当前用户头像字段
    """
    if not file.filename:
        raise ValidationError("文件名不能为空")

    file_url = await storage.save(file, sub_dir="avatars")

    current_user.avatar = file_url
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)

    from app.api.deps import invalidate_user_cache
    invalidate_user_cache(current_user.id)

    return Response(
        code=200,
        success=True,
        message="头像上传并更新成功",
        data={"url": file_url}
    )
