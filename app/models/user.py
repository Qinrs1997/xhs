"""用户模型"""
from datetime import datetime
from app.core.timezone import now_utc
from sqlalchemy import String, Boolean, JSON, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel
from app.models.role import Role


class User(BaseModel):
    """用户模型"""
    __tablename__ = "users"
    __table_args__ = {"comment": "用户表"}

    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
        comment="用户名"
    )
    email: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="邮箱"
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="密码哈希"
    )
    full_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="全名"
    )
    phone: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
        comment="手机号"
    )
    bio: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
        comment="个人简介"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否激活"
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否超级用户"
    )
    avatar: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="用户头像地址",
        default="https://avatars.githubusercontent.com/u/44761321"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="最后登录时间"
    )
    last_login_ip: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
        comment="最后登录IP"
    )
    # 菜单偏好设置：存储用户隐藏的菜单路径列表
    # 格式: {"hidden_menus": ["/xhs", "/system/logs"]}
    menu_preferences: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="菜单偏好设置(JSON)"
    )

    # ==================== 会员 + 积分字段 ====================
    credits: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
        comment="当前可用积分"
    )
    vip_level: Mapped[str] = mapped_column(
        String(20),
        default="free",
        nullable=False,
        server_default="free",
        index=True,
        comment="会员等级: free/plus/pro/max"
    )
    vip_expire_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        default=None,
        comment="会员到期时间"
    )
    total_credits_used: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
        comment="累计消耗积分"
    )
    invite_code: Mapped[str | None] = mapped_column(
        String(20),
        unique=True,
        nullable=True,
        default=None,
        comment="邀请码"
    )
    invited_by: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        index=True,
        comment="邀请人用户ID"
    )
    auto_renew: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        server_default="1",
        comment="是否自动续费"
    )

    # 角色关系
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )

    @property
    def is_vip_active(self) -> bool:
        """VIP 是否有效（未过期且非 free）"""
        if self.vip_level == "free":
            return False
        if self.vip_expire_at is None:
            return True  # 永久 VIP
        return self.vip_expire_at > now_utc().replace(tzinfo=None)

    @property
    def actual_vip_level(self) -> str:
        """实际生效的 VIP 等级（过期则降为 free）"""
        return self.vip_level if self.is_vip_active else "free"

