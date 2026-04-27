"""应用配置模块（使用 TOML 按需读取）

按职责拆为 4 个子模块，对外 API 与旧单文件完全兼容：

- `schema.py`        — Pydantic `Settings` 类（所有字段声明）
- `toml_loader.py`   — TOML 加载 + 路径映射 + 扁平化
- `safety_check.py`  — 生产环境安全检查
- `__init__.py`      — `get_settings()` 组合 + 全局 `settings` 单例 + 便捷访问

配置加载优先级（由高到低，**env 最高**）:
    环境变量 > settings.{env}.local.toml > settings.local.toml
    > settings.{env}.toml > settings.toml > 代码默认值
"""
import os
from functools import lru_cache
from pathlib import Path

# 在 Settings 实例化前把 backend/.env 注入到 os.environ,这样:
# 1. TOML 合并阶段能通过 env_present_fields 把 .env 中出现的字段从 flat_config 剔除
# 2. Pydantic Settings 能从 os.environ 读到 MYSQL_USER / SECRET_KEY 等敏感值
# 测试环境(APP_ENV=test)不加载 .env,避免开发机密码/Redis 真实地址污染 CI
if os.getenv("APP_ENV", "dev") != "test":
    try:
        from dotenv import load_dotenv
        # backend/.env 位于本文件上溯 4 层(config/ -> core/ -> app/ -> backend/)
        _backend_dir = Path(__file__).resolve().parent.parent.parent.parent
        _dotenv_path = _backend_dir / ".env"
        if _dotenv_path.exists():
            # override=False:外部已设置的环境变量依旧优先(Docker/CI 场景)
            load_dotenv(_dotenv_path, override=False)
    except ImportError:  # pragma: no cover - python-dotenv 可选
        pass

from .safety_check import production_safety_check
from .schema import Settings
from .toml_loader import (
    deep_merge,
    extract_settings_from_toml,
    get_nested_value,
    load_toml_config,
)


@lru_cache
def get_settings() -> Settings:
    """获取配置实例（缓存）

    加载流程:
    1. 从 APP_ENV 环境变量确定运行环境（dev/test/prod）
    2. 加载 config/settings.toml（默认配置）
    3. 加载 config/settings.{env}.toml（环境配置，覆盖默认）
    4. 加载 config/settings.local.toml 与 settings.{env}.local.toml（服务器本地覆盖）
    5. 读取环境变量（最高优先级，覆盖所有）

    ⚠️ 实现要点: Pydantic-settings 原生规则是 init kwargs > env；
    但我们把 TOML 值作为 init kwargs 传入，会反向覆盖 env。
    因此此处显式**把 env 中已有的字段从 flat_config 剔除**，
    让 pydantic-settings 从 env 读取，保证 env 最高优先级。
    """
    env = os.getenv("APP_ENV", "dev")

    toml_config = load_toml_config(env)
    flat_config = extract_settings_from_toml(toml_config)

    # 如果 env 中已有对应变量，从 flat_config 里移除该字段
    # 这样 Pydantic Settings 会从 env 读取，不会被 TOML 反向覆盖
    settings_field_names = set(Settings.model_fields.keys())
    env_present_fields = {
        name for name in settings_field_names if name in os.environ
    }
    for field_name in env_present_fields:
        flat_config.pop(field_name, None)

    settings = Settings(**flat_config)

    # 生产环境：自动关闭 OpenAPI 文档（除非环境变量显式开启）
    if settings.is_production:
        if os.getenv("DOCS_URL") is None:
            settings.DOCS_URL = None
        if os.getenv("REDOC_URL") is None:
            settings.REDOC_URL = None
        if os.getenv("OPENAPI_URL") is None:
            settings.OPENAPI_URL = None
        production_safety_check(settings)

    return settings


# 全局配置实例
settings = get_settings()


# 便捷访问函数
def get_database_url() -> str:
    """获取数据库连接字符串"""
    return settings.DATABASE_URL


def is_debug_mode() -> bool:
    """是否是调试模式"""
    return settings.DEBUG


def get_cors_origins() -> list[str]:
    """获取 CORS 允许的源"""
    return settings.BACKEND_CORS_ORIGINS


# 保留旧私有名（`_production_safety_check`）向后兼容
_production_safety_check = production_safety_check


__all__ = [
    "Settings",
    "deep_merge",
    "extract_settings_from_toml",
    "get_cors_origins",
    "get_database_url",
    "get_nested_value",
    "get_settings",
    "is_debug_mode",
    "load_toml_config",
    "production_safety_check",
    "settings",
]
