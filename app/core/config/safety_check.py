"""生产环境安全检查

在 prod 环境下,确保关键安全配置已正确设置,防止默认值上线。
"""
import math
from collections import Counter

from .schema import Settings


def _shannon_entropy(value: str) -> float:
    """估算字符串的 Shannon 熵(单位:bit/char)

    用于辅助判定 SECRET_KEY 是否"看起来像随机串":
    - `secrets.token_urlsafe(32)` 约 5.5 bit/char
    - 重复字符(如 `aaaaaaa`)接近 0 bit/char
    阈值:≥3.0 bit/char 就认为是够随机的字符串(保守不误杀真实秘钥)。
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def production_safety_check(settings: Settings) -> None:
    """生产环境安全检查

    Raises:
        ValueError: 安全配置不符合生产环境要求
    """
    errors: list[str] = []

    # ========== SECRET_KEY ==========
    unsafe_keys = {"", "your-secret-key-change-this-in-production", "changeme"}
    if not settings.SECRET_KEY or settings.SECRET_KEY in unsafe_keys:
        errors.append("SECRET_KEY 未设置或使用了不安全的默认值")
    else:
        if len(settings.SECRET_KEY) < 32:
            errors.append(
                f"SECRET_KEY 长度不足 32 位(当前 {len(settings.SECRET_KEY)}),"
                "请用 `python -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成"
            )
        if _shannon_entropy(settings.SECRET_KEY) < 3.0:
            errors.append(
                "SECRET_KEY 熵过低,疑似键盘乱敲或重复字符,请使用密码学随机串"
            )
        if settings.MYSQL_PASSWORD and settings.SECRET_KEY == settings.MYSQL_PASSWORD:
            errors.append("SECRET_KEY 不能与 MYSQL_PASSWORD 相同")
        if (
            settings.REDIS_PASSWORD
            and settings.SECRET_KEY == settings.REDIS_PASSWORD
        ):
            errors.append("SECRET_KEY 不能与 REDIS_PASSWORD 相同")

    # ========== MYSQL ==========
    if not settings.MYSQL_PASSWORD:
        errors.append("MYSQL_PASSWORD 未设置")

    # ========== CORS ==========
    if settings.BACKEND_CORS_ORIGINS == ["*"]:
        errors.append("CORS origins 不能为通配符 ['*'],请设置具体域名")

    # ========== DEBUG ==========
    if settings.DEBUG:
        errors.append("生产环境不应开启 DEBUG 模式")

    # ========== TrustedHost ==========
    if settings.ALLOWED_HOSTS == ["*"]:
        errors.append(
            "ALLOWED_HOSTS 不能为 ['*'],请在 config/settings.prod.toml 的 "
            "[security] allowed_hosts 填具体域名以启用 TrustedHostMiddleware"
        )

    # ========== Bootstrap Admin ==========
    unsafe_passwords = {"admin123", "password", "123456", "admin", ""}
    if settings.BOOTSTRAP_ADMIN_PASSWORD in unsafe_passwords:
        errors.append("BOOTSTRAP_ADMIN_PASSWORD 使用了不安全的默认密码,请修改")
    elif len(settings.BOOTSTRAP_ADMIN_PASSWORD) < 8:
        errors.append("BOOTSTRAP_ADMIN_PASSWORD 长度不足 8 位")

    # ========== Redis ==========
    if settings.REDIS_ENABLED and not settings.REDIS_PASSWORD:
        errors.append(
            "REDIS_ENABLED=True 但未设置 REDIS_PASSWORD,生产环境 Redis 必须鉴权"
        )

    # ========== 登录锁定 ==========
    if settings.MAX_LOGIN_ATTEMPTS <= 0:
        errors.append(
            "MAX_LOGIN_ATTEMPTS=0 代表无登录锁定,生产环境必须大于 0(建议 5)"
        )

    # ========== Metrics ==========
    if settings.METRICS_ENABLED:
        allowed_ips = settings.METRICS_ALLOWED_IPS or []
        if not allowed_ips and not settings.METRICS_AUTH_TOKEN:
            errors.append(
                "METRICS_ENABLED=True 但 METRICS_ALLOWED_IPS 与 METRICS_AUTH_TOKEN 都为空,"
                "请至少配置其一(建议同时配置 IP 白名单 + 内网隔离)"
            )

    # ========== AUTO_MIGRATE ==========
    if settings.AUTO_MIGRATE:
        errors.append(
            "生产环境建议 AUTO_MIGRATE=false,改由 CI/Ops 独立执行 `alembic upgrade head`"
        )

    if errors:
        error_msg = "生产环境安全检查失败:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)
