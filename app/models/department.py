"""部门模型

支持无限层级的树形结构部门管理。
"""
from typing import Optional
from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class Department(BaseModel):
    """
    部门模型

    支持无限层级的树形结构。
    """
    __tablename__ = "departments"

    # 部门名称
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="部门名称"
    )

    # 部门编码（唯一标识，如 TECH、HR、SALES）
    code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="部门编码"
    )

    # 父部门（自关联，实现树形结构）
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父部门ID"
    )

    # 部门层级（根部门为1，便于查询）
    level: Mapped[int] = mapped_column(
        Integer,
        default=1,
        comment="部门层级"
    )

    # 排序（同级部门排序）
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        comment="排序顺序"
    )

    # 部门负责人（关联用户）
    leader_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="部门负责人ID"
    )

    # 部门描述
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="部门描述"
    )

    # 是否启用
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        comment="是否启用"
    )

    # 关系（默认懒加载：需要时显式 selectinload 预加载；
    # 自引用关系 selectin 容易导致连锁加载，改回默认更安全）
    parent = relationship(
        "Department",
        remote_side="Department.id",
        backref="children",
    )

    leader = relationship(
        "User",
        foreign_keys=[leader_id],
        backref="led_departments",
    )

    def __repr__(self) -> str:
        return f"<Department(id={self.id}, name='{self.name}', code='{self.code}')>"


class UserDepartment(BaseModel):
    """
    用户-部门关联表

    多对多关系，一个用户可以属于多个部门。
    同一用户在同一部门只能有一条记录（通过唯一约束保证）。
    """
    __tablename__ = "user_departments"
    __table_args__ = (
        UniqueConstraint('user_id', 'department_id', name='uq_user_department_user_dept'),
        {"comment": "用户-部门关联表"},
    )

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )

    department_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="部门ID"
    )

    # 是否是主部门（一个用户只能有一个主部门）
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="是否主部门"
    )

    # 在该部门的职位
    position: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="职位"
    )

    # 关系（默认懒加载：已有的 CRUD 查询均显式 selectinload，模型层不再强制 eager）
    user = relationship("User", backref="department_links")
    department = relationship("Department", backref="user_links")

    def __repr__(self) -> str:
        return f"<UserDepartment(user_id={self.user_id}, department_id={self.department_id})>"
