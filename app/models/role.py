"""角色与用户角色模型"""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel

if TYPE_CHECKING:
    # 仅用于类型检查；运行时由 SQLAlchemy 按字符串解析 "User" 模型
    from app.models.user import User  # noqa: F401


class Role(BaseModel):
    """角色表"""
    __tablename__ = "roles"
    __table_args__ = {"comment": "角色表"}

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="角色名称（唯一）")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="角色描述")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")

    # 关系：角色拥有的用户（反向关系，默认懒加载；列角色时不会自动加载所有用户，避免管理员角色可能的大列表爆表）
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_roles",
        back_populates="roles",
    )


class UserRole(Base):
    """用户-角色关联表"""
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        {"comment": "用户角色关联表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, comment="主键ID")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID")
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, comment="角色ID")


