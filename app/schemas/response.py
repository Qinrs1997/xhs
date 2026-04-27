"""通用响应 Schema 和分页工具"""
from typing import Generic, TypeVar, Optional, Any, List
from pydantic import BaseModel, Field

from app.core.config import settings

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    """统一响应格式"""
    code: int = Field(default=200, description="状态码")
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="success", description="消息")
    data: Optional[T] = Field(default=None, description="数据")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据结构"""
    items: List[T] = Field(default=[], description="数据列表")
    total: int = Field(default=0, description="总数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")
    pages: int = Field(default=0, description="总页数")

    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int = 1,
        page_size: int = 20,
    ) -> "PaginatedData[T]":
        """创建分页数据"""
        pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应（包装整个响应）"""
    code: int = Field(default=200, description="状态码")
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="success", description="消息")
    data: Optional[PaginatedData[T]] = Field(default=None, description="分页数据")


class CursorPaginatedData(BaseModel, Generic[T]):
    """游标分页数据结构（大表深翻页推荐）"""
    items: List[T] = Field(default=[], description="数据列表")
    next_cursor: Optional[int] = Field(default=None, description="下一页游标（None 表示没有更多数据）")
    page_size: int = Field(default=20, description="每页数量")
    has_more: bool = Field(default=False, description="是否还有更多数据")

    @classmethod
    def create(
        cls,
        items: List[T],
        next_cursor: Optional[int],
        page_size: int = 20,
    ) -> "CursorPaginatedData[T]":
        """创建游标分页数据"""
        return cls(
            items=items,
            next_cursor=next_cursor,
            page_size=page_size,
            has_more=next_cursor is not None,
        )


class ErrorResponse(BaseModel):
    """错误响应"""
    code: int = Field(..., description="错误码")
    error_code: str = Field(default="ERROR", description="错误代码")
    message: str = Field(..., description="错误消息")
    detail: Optional[Any] = Field(None, description="错误详情")


# ==================== 分页参数工具 ====================

class PaginationParams:
    """
    分页参数

    使用方法：
        from fastapi import Depends
        from app.schemas.response import PaginationParams

        @router.get("/items")
        def list_items(
            pagination: PaginationParams = Depends(),
            db: Session = Depends(get_db),
        ):
            items = db.query(Item).offset(pagination.skip).limit(pagination.limit).all()
            total = db.query(Item).count()
            return Response(
                data=PaginatedData.create(
                    items=items,
                    total=total,
                    page=pagination.page,
                    page_size=pagination.page_size,
                )
            )
    """

    def __init__(
        self,
        page: int = 1,
        page_size: int = 20,
    ):
        # 限制 page_size 范围
        self.page = max(1, page)
        self.page_size = min(max(1, page_size), settings.MAX_PAGE_SIZE)

    @property
    def skip(self) -> int:
        """计算跳过的记录数"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """返回每页记录数"""
        return self.page_size
