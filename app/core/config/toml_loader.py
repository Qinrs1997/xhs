"""TOML 配置加载与扁平化

从 `config/settings.toml`、`config/settings.{env}.toml` 和本地覆盖文件加载分层配置，
再按 `FIELD_MAPPINGS` 映射扁平化成 Pydantic Settings 可以接受的 kwargs。
"""
from pathlib import Path
from typing import Any

try:  # Python 3.11+ 自带 tomllib，3.10 使用 tomli
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[assignment]


# TOML 路径 -> Settings 字段名 -> 默认值
# 新增配置时，只需在这里加一行映射即可
FIELD_MAPPINGS: list[tuple[str, str, Any]] = [
    # app 配置
    ("app.name", "PROJECT_NAME", "挽梦图文生成"),
    ("app.description", "DESCRIPTION", "小红书 AI 图文创作平台"),
    ("app.version", "VERSION", "1.0.0"),
    ("app.debug", "DEBUG", False),
    ("app.env", "APP_ENV", "dev"),
    ("app.host", "APP_HOST", "0.0.0.0"),
    ("app.port", "APP_PORT", 8000),
    ("app.workers", "APP_WORKERS", 1),
    ("app.api_prefix", "API_V1_PREFIX", "/api/v1"),
    ("app.docs_url", "DOCS_URL", "/docs"),
    ("app.redoc_url", "REDOC_URL", "/redoc"),
    ("app.openapi_url", "OPENAPI_URL", "/openapi.json"),

    # database 配置（database.* -> MYSQL_*）
    ("database.host", "MYSQL_HOST", "localhost"),
    ("database.port", "MYSQL_PORT", 3306),
    ("database.name", "MYSQL_DATABASE", "fastapi_db"),
    ("database.user", "MYSQL_USER", "root"),
    ("database.password", "MYSQL_PASSWORD", ""),
    ("database.charset", "MYSQL_CHARSET", "utf8mb4"),
    ("database.pool_class", "DB_POOL_CLASS", "queue"),
    ("database.pool_size", "DB_POOL_SIZE", 10),
    ("database.max_overflow", "DB_MAX_OVERFLOW", 20),
    ("database.pool_timeout", "DB_POOL_TIMEOUT", 30),
    ("database.pool_recycle", "DB_POOL_RECYCLE", 3600),
    ("database.pool_pre_ping", "DB_POOL_PRE_PING", True),
    ("database.echo", "DB_ECHO", False),
    ("database.query_timeout", "DB_QUERY_TIMEOUT", 30),
    ("database.connect_timeout", "DB_CONNECT_TIMEOUT", 10),
    ("database.read_timeout", "DB_READ_TIMEOUT", 30),
    ("database.write_timeout", "DB_WRITE_TIMEOUT", 30),

    # JWT 配置
    ("jwt.secret_key", "SECRET_KEY", "your-secret-key-change-this-in-production"),
    ("jwt.algorithm", "ALGORITHM", "HS256"),
    ("jwt.access_token_expire_minutes", "ACCESS_TOKEN_EXPIRE_MINUTES", 30),
    ("jwt.refresh_token_expire_days", "REFRESH_TOKEN_EXPIRE_DAYS", 7),

    # password 配置
    ("password.min_length", "PASSWORD_MIN_LENGTH", 6),
    ("password.max_length", "PASSWORD_MAX_LENGTH", 50),
    ("password.bcrypt_rounds", "PASSWORD_BCRYPT_ROUNDS", 12),
    ("password.max_login_attempts", "MAX_LOGIN_ATTEMPTS", 0),
    ("password.lockout_duration", "LOCKOUT_DURATION", 300),

    # CORS 配置
    ("cors.origins", "BACKEND_CORS_ORIGINS", ["*"]),
    ("cors.allow_credentials", "CORS_ALLOW_CREDENTIALS", True),
    ("cors.allow_methods", "CORS_ALLOW_METHODS", ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
    ("cors.allow_headers", "CORS_ALLOW_HEADERS", ["*"]),
    ("cors.max_age", "CORS_MAX_AGE", 3600),

    # logging 配置
    ("logging.level", "LOG_LEVEL", "INFO"),
    ("logging.file.path", "LOG_FILE", "logs/app.log"),
    ("logging.file.max_bytes", "LOG_MAX_BYTES", 10485760),
    ("logging.file.backup_count", "LOG_BACKUP_COUNT", 5),
    ("logging.quiet_routes.paths", "QUIET_ROUTES", []),

    # pagination 配置
    ("pagination.default_page_size", "DEFAULT_PAGE_SIZE", 20),
    ("pagination.max_page_size", "MAX_PAGE_SIZE", 100),

    # upload 配置
    ("upload.enabled", "UPLOAD_ENABLED", False),
    ("upload.max_file_size", "MAX_UPLOAD_SIZE", 5242880),
    ("upload.upload_dir", "UPLOAD_DIR", "uploads/"),

    # Redis 配置
    ("cache.enabled", "REDIS_ENABLED", False),
    ("cache.redis.host", "REDIS_HOST", "localhost"),
    ("cache.redis.port", "REDIS_PORT", 6379),
    ("cache.redis.db", "REDIS_DB", 0),
    ("cache.redis.password", "REDIS_PASSWORD", ""),
    ("cache.redis.max_connections", "REDIS_MAX_CONNECTIONS", 10),

    # rate_limit 配置
    ("rate_limit.enabled", "RATE_LIMIT_ENABLED", False),
    ("rate_limit.requests_per_minute", "RATE_LIMIT_REQUESTS_PER_MINUTE", 60),
    ("rate_limit.burst_size", "RATE_LIMIT_BURST_SIZE", 10),

    # email 配置
    ("email.enabled", "EMAIL_ENABLED", False),
    ("email.smtp_host", "EMAIL_SMTP_HOST", "smtp.qq.com"),
    ("email.smtp_port", "EMAIL_SMTP_PORT", 465),
    ("email.smtp_tls", "EMAIL_SMTP_TLS", True),
    ("email.from_addr", "EMAIL_FROM", ""),
    ("email.from_name", "EMAIL_FROM_NAME", "挽梦图文生成"),
    ("email.password", "EMAIL_PASSWORD", ""),

    # monitoring 配置
    ("monitoring.metrics_enabled", "METRICS_ENABLED", False),
    ("monitoring.metrics_path", "METRICS_PATH", "/metrics"),
    ("monitoring.metrics_allowed_ips", "METRICS_ALLOWED_IPS", None),
    ("monitoring.metrics_auth_token", "METRICS_AUTH_TOKEN", None),

    # security 配置(TrustedHost + 登录锁定,security.max_login_attempts 会覆盖 password.*)
    ("security.allowed_hosts", "ALLOWED_HOSTS", None),
    ("security.headers_enabled", "SECURITY_HEADERS_ENABLED", None),
    ("security.hsts_max_age", "HSTS_MAX_AGE", None),
    ("security.max_login_attempts", "MAX_LOGIN_ATTEMPTS", None),
    ("security.lockout_duration", "LOCKOUT_DURATION", None),

    # database.auto_migrate(生产建议关,由 CI/Ops 手工迁移)
    ("database.auto_migrate", "AUTO_MIGRATE", None),

    # bootstrap admin
    ("bootstrap.admin_username", "BOOTSTRAP_ADMIN_USERNAME", "admin"),
    ("bootstrap.admin_password", "BOOTSTRAP_ADMIN_PASSWORD", "admin123"),
    ("bootstrap.admin_email", "BOOTSTRAP_ADMIN_EMAIL", "admin@example.com"),
    ("bootstrap.admin_full_name", "BOOTSTRAP_ADMIN_FULL_NAME", "Administrator"),

    # 前端地址
    ("app.frontend_url", "FRONTEND_URL", None),

    # 支付配置 — 默认值为 None，不存在于 TOML 时跳过，由 .env 提供
    ("payment.mode", "PAYMENT_MODE", None),
    ("payment.alipay.app_id", "ALIPAY_APP_ID", None),
    ("payment.alipay.private_key", "ALIPAY_PRIVATE_KEY", None),
    ("payment.alipay.public_key", "ALIPAY_PUBLIC_KEY", None),
    ("payment.alipay.notify_url", "ALIPAY_NOTIFY_URL", None),
    ("payment.alipay.return_url", "ALIPAY_RETURN_URL", None),
    ("payment.alipay.sandbox", "ALIPAY_SANDBOX", None),
]


def load_toml_config(env: str = "dev") -> dict[str, Any]:
    """从 TOML 文件加载配置（default + env + local 覆盖）"""
    # 从本文件上溯到 backend 根目录（三层：config/ -> core/ -> app/ -> backend/）
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    config_dir = base_dir / "config"

    default_config_file = config_dir / "settings.toml"
    env_config_file = config_dir / f"settings.{env}.toml"
    local_config_file = config_dir / "settings.local.toml"
    env_local_config_file = config_dir / f"settings.{env}.local.toml"

    config: dict[str, Any] = {}

    if default_config_file.exists():
        with open(default_config_file, "rb") as f:
            config = tomllib.load(f) or {}

    if env_config_file.exists():
        with open(env_config_file, "rb") as f:
            env_config = tomllib.load(f) or {}
            config = deep_merge(config, env_config)

    # 服务器本地覆盖文件放在 tracked 配置之后加载,并通过 .gitignore 保持不入库。
    # 用途:生产库密码、沙箱/支付差异、域名白名单等服务器特有配置。
    for local_file in (local_config_file, env_local_config_file):
        if local_file.exists():
            with open(local_file, "rb") as f:
                local_config = tomllib.load(f) or {}
                config = deep_merge(config, local_config)

    return config


def deep_merge(dict1: dict, dict2: dict) -> dict:
    """深度合并两个字典（dict2 的值优先）"""
    result = dict1.copy()

    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def get_nested_value(config: dict, path: str, default: Any = None) -> Any:
    """从嵌套字典中按路径读取值

    例如：
        config = {"app": {"name": "FastAPI"}}
        get_nested_value(config, "app.name")  # 返回 "FastAPI"
        get_nested_value(config, "app.port", 8000)  # 不存在时返回 8000
    """
    keys = path.split(".")
    value = config

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    return value


def extract_settings_from_toml(toml_config: dict) -> dict:
    """从 TOML 配置中按需提取 Settings 需要的字段

    使用 `FIELD_MAPPINGS` 中定义的路径映射，只提取我们关心的字段。
    """
    result = {}
    for toml_path, field_name, default_value in FIELD_MAPPINGS:
        value = get_nested_value(toml_config, toml_path, default_value)
        # 跳过 None：TOML 中未定义时不覆盖 .env
        if value is None:
            continue
        # 跳过空字符串：让 pydantic-settings 从 .env / 环境变量读取
        # 这样 TOML 中 secret_key = "" / password = "" 不会覆盖 .env 中的实际值
        if isinstance(value, str) and value == "":
            continue
        result[field_name] = value

    return result
