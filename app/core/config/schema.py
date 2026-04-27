"""Pydantic Settings 配置 Schema"""
import logging
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

_cfg_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """持久化应用配置类（增强验证版）

    采用 Pydantic v2 进行严格验证。
    """

    # ==================== 运行环境 ====================
    APP_ENV: str = Field(default="dev", description="运行环境：dev/test/prod")

    # ==================== 应用基本配置 ====================
    PROJECT_NAME: str = Field(default="挽梦图文生成")
    DESCRIPTION: str = Field(default="小红书 AI 图文创作平台")
    VERSION: str = Field(default="1.0.0")
    API_V1_PREFIX: str = Field(default="/api/v1")
    DEBUG: bool = Field(default=False)

    APP_HOST: str = Field(default="0.0.0.0")
    APP_PORT: int = Field(default=8000)
    APP_WORKERS: int = Field(default=1)

    DOCS_URL: Optional[str] = Field(default="/docs")
    REDOC_URL: Optional[str] = Field(default="/redoc")
    OPENAPI_URL: Optional[str] = Field(default="/openapi.json")

    # ==================== 数据库配置 (强制验证) ====================
    MYSQL_HOST: str = Field(..., description="MySQL 主机 (必填)")
    MYSQL_PORT: int = Field(default=3306)
    MYSQL_USER: str = Field(..., description="MySQL 用户 (必填)")
    MYSQL_PASSWORD: str = Field(..., description="MySQL 密码 (必填)")
    MYSQL_DATABASE: str = Field(..., description="数据库名 (必填)")
    MYSQL_CHARSET: str = Field(default="utf8mb4")

    DB_POOL_CLASS: str = Field(default="queue")
    DB_POOL_SIZE: int = Field(default=10)
    DB_MAX_OVERFLOW: int = Field(default=20)
    DB_POOL_TIMEOUT: int = Field(default=30)
    DB_POOL_RECYCLE: int = Field(default=3600)
    DB_POOL_PRE_PING: bool = Field(default=True)
    DB_ECHO: bool = Field(default=False)

    DB_QUERY_TIMEOUT: int = Field(default=30)
    DB_CONNECT_TIMEOUT: int = Field(default=10)
    DB_READ_TIMEOUT: int = Field(default=30)
    DB_WRITE_TIMEOUT: int = Field(default=30)

    # 启动时是否自动执行 Alembic 迁移:
    # - dev/test 默认 True,开发体验好
    # - prod 强烈建议 False,由 Ops 在灰度前独立执行 `alembic upgrade head`,
    #   避免"多 worker 同时跑迁移"或"开发者误发生产导致表结构被覆盖"的风险
    AUTO_MIGRATE: bool = Field(
        default=True,
        description="启动时自动 alembic upgrade head(生产建议关闭,由 Ops 手工执行)",
    )

    # ==================== 安全与认证 (强制验证) ====================
    SECRET_KEY: str = Field(..., description="JWT 密钥 (必填)")
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    PASSWORD_MIN_LENGTH: int = Field(default=6)
    PASSWORD_MAX_LENGTH: int = Field(default=50)
    PASSWORD_BCRYPT_ROUNDS: int = Field(default=12)
    MAX_LOGIN_ATTEMPTS: int = Field(default=0)                     # 0=不限制
    LOCKOUT_DURATION: int = Field(default=300)                     # 锁定时长（秒）

    # ==================== CORS 配置 ====================
    BACKEND_CORS_ORIGINS: list[str] = Field(default=["*"])
    CORS_ALLOW_CREDENTIALS: bool = Field(default=True)
    CORS_ALLOW_METHODS: list[str] = Field(default=["*"])
    CORS_ALLOW_HEADERS: list[str] = Field(default=["*"])
    CORS_MAX_AGE: int = Field(default=3600)

    # ==================== 其他模块配置 ====================
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="logs/app.log")                  # 日志目录取自此路径的 parent
    LOG_MAX_BYTES: int = Field(default=10485760)                   # 保留兼容，按天切割后不再使用
    LOG_BACKUP_COUNT: int = Field(default=30)                      # 日志保留天数
    QUIET_ROUTES: list[str] = Field(default=[])                    # 静默路由（日志降级为 DEBUG）

    DEFAULT_PAGE_SIZE: int = Field(default=20)
    MAX_PAGE_SIZE: int = Field(default=100)

    REDIS_ENABLED: bool = Field(default=False)
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    REDIS_PASSWORD: str = Field(default="")
    REDIS_MAX_CONNECTIONS: int = Field(default=10)

    RATE_LIMIT_ENABLED: bool = Field(default=False)
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=60)
    RATE_LIMIT_BURST_SIZE: int = Field(default=10)

    UPLOAD_ENABLED: bool = Field(default=False)
    MAX_UPLOAD_SIZE: int = Field(default=5242880)
    UPLOAD_DIR: str = Field(default="uploads/")

    # ==================== 邮件配置 ====================
    EMAIL_ENABLED: bool = Field(default=False)
    EMAIL_SMTP_HOST: str = Field(default="smtp.qq.com")
    EMAIL_SMTP_PORT: int = Field(default=465)
    EMAIL_SMTP_TLS: bool = Field(default=True)
    EMAIL_FROM: str = Field(default="")
    EMAIL_FROM_NAME: str = Field(default="挽梦图文生成")
    EMAIL_PASSWORD: str = Field(default="")

    # ==================== 监控配置 ====================
    METRICS_ENABLED: bool = Field(default=False)
    METRICS_PATH: str = Field(default="/metrics")
    METRICS_ALLOWED_IPS: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description=(
            "允许访问 /metrics 的客户端 IP 白名单(支持完整 IP 或 CIDR)。"
            "设为空列表则关闭白名单(不推荐生产使用)。"
            "默认仅允许本机,反代/Prom 采集器请在此追加其 IP/CIDR。"
        ),
    )
    METRICS_AUTH_TOKEN: str = Field(
        default="",
        description=(
            "访问 /metrics 需要的 Bearer token;留空则仅按 IP 白名单控制。"
            "推荐在生产额外配合反代网络隔离使用。"
        ),
    )

    # ==================== 主机头保护 / 安全响应头 ====================
    ALLOWED_HOSTS: list[str] = Field(
        default_factory=lambda: ["*"],
        description=(
            "TrustedHostMiddleware 允许的 Host 头白名单(防 Host 头投毒/缓存投毒)。"
            "生产必须改为具体域名,默认 ['*'] 仅供本地开发使用。"
        ),
    )
    SECURITY_HEADERS_ENABLED: bool = Field(
        default=True,
        description="是否对 API 响应自动附加 HSTS/X-Frame-Options 等安全头",
    )
    HSTS_MAX_AGE: int = Field(
        default=31536000,
        description="HSTS max-age 秒数(默认 1 年);仅 HTTPS 场景生效",
    )

    # ==================== 前端地址 ====================
    FRONTEND_URL: str = Field(
        default="http://localhost:3000",
        description="前端地址，用于邀请链接、支付回调等",
    )
    PUBLIC_API_BASE: str = Field(
        default="",
        description=(
            "对外可访问的后端基址(用于给用户/第三方生成可点击链接,例如 mock 支付页面)。"
            "为空时回落到 http://127.0.0.1:{APP_PORT}。Docker/远程部署时应显式配置。"
        ),
    )

    # ==================== 支付配置 ====================
    PAYMENT_MODE: str = Field(default="mock", description="支付模式: mock/alipay")
    ALIPAY_APP_ID: str = Field(default="", description="支付宝 APPID")
    ALIPAY_PRIVATE_KEY: str = Field(default="", description="应用私钥")
    ALIPAY_PUBLIC_KEY: str = Field(default="", description="支付宝公钥")
    ALIPAY_NOTIFY_URL: str = Field(default="", description="支付宝异步回调URL")
    ALIPAY_RETURN_URL: str = Field(default="", description="支付宝同步跳转URL")
    ALIPAY_SANDBOX: bool = Field(default=True, description="是否使用沙箱环境")

    BOOTSTRAP_ADMIN_USERNAME: str = Field(default="admin")
    BOOTSTRAP_ADMIN_PASSWORD: str = Field(default="admin123")
    BOOTSTRAP_ADMIN_EMAIL: str = Field(default="admin@example.com")
    BOOTSTRAP_ADMIN_FULL_NAME: str = Field(default="Administrator")

    model_config = {
        "extra": "ignore",
        "env_file": ".env",
        "case_sensitive": True,
    }

    @model_validator(mode="after")
    def _check_cors_credentials_conflict(self) -> "Settings":
        """浏览器/Starlette 规范不允许 `allow_origins=["*"]` 与 `allow_credentials=True` 同时成立。

        - prod 环境:由 `production_safety_check` 统一抛错(已禁止 ["*"])。
        - dev/test 环境:为避免开发体验断裂,自动把 credentials 降级为 False,
          并记录 warning 提示。
        """
        if (
            self.BACKEND_CORS_ORIGINS == ["*"]
            and self.CORS_ALLOW_CREDENTIALS
        ):
            _cfg_logger.warning(
                "CORS 配置冲突:allow_origins=['*'] 与 allow_credentials=True "
                "不兼容(浏览器会拒绝携带 Cookie/Authorization)。"
                "已自动降级 CORS_ALLOW_CREDENTIALS=False。"
                "正式环境请改为具体域名白名单。"
            )
            object.__setattr__(self, "CORS_ALLOW_CREDENTIALS", False)
        return self

    @property
    def DATABASE_URL(self) -> str:
        """构建数据库连接字符串"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset={self.MYSQL_CHARSET}"
        )

    @property
    def is_development(self) -> bool:
        """是否是开发环境"""
        return self.APP_ENV == "dev"

    @property
    def is_production(self) -> bool:
        """是否是生产环境"""
        return self.APP_ENV == "prod"

    @property
    def is_test(self) -> bool:
        """是否是测试环境"""
        return self.APP_ENV == "test"
