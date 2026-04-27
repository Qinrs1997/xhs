"""数据库模型基类

提供两种基础模型：
- BaseModel: 标准模型（含 id, created_at, updated_at）
- SoftDeleteModel: 软删除模型（额外含 is_deleted, deleted_at）
"""
from datetime import datetime
from typing import Any, Optional
from sqlalchemy import Integer, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase


class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


class BaseModel(Base):
    """
    基础模型类，提供通用字段

    字段：
    - id: 主键 ID
    - created_at: 创建时间
    - updated_at: 更新时间

    所有业务模型都应该继承此类
    """
    __abstract__ = True

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        comment="主键ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间"
    )

    # 审计字段：由业务代码或拦截器自动填充
    creator_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="创建者ID")
    updater_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="更新者ID")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }

    def __repr__(self) -> str:
        """字符串表示"""
        attrs = ", ".join(
            f"{k}={v!r}"
            for k, v in self.to_dict().items()
        )
        return f"{self.__class__.__name__}({attrs})"


class SoftDeleteModel(BaseModel):
    """
    软删除模型类

    在 BaseModel 基础上增加软删除支持：
    - is_deleted: 是否已删除
    - deleted_at: 删除时间

    使用软删除的模型应继承此类。

    使用示例：
        class Article(SoftDeleteModel):
            __tablename__ = "articles"
            title: Mapped[str] = mapped_column(String(200))
    """
    __abstract__ = True

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="是否已删除"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="删除时间"
    )

    def soft_delete(self) -> None:
        """标记为已删除（使用 UTC 时间）"""
        from datetime import timezone
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self) -> None:
        """恢复已删除的记录"""
        self.is_deleted = False
        self.deleted_at = None
