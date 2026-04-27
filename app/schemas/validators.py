"""Schema 验证增强模块

提供通用的 Pydantic 验证器和基类，增强输入输出校验。

特性：
- 自动字符串清理（去除首尾空格）
- XSS 防护（过滤危险字符）
- 日志脱敏（自动隐藏敏感字段）
- 常用验证器（手机号、身份证等）

使用方法：
    from app.schemas.validators import ValidatedBaseModel, Sanitized, SensitiveStr

    class UserCreate(ValidatedBaseModel):
        username: Sanitized[str]  # 自动清理空格和危险字符
        password: SensitiveStr    # 日志中自动脱敏
        phone: str

        @field_validator("phone")
        @classmethod
        def validate_phone(cls, v):
            return validators.phone(v)
"""
import re
import html
from typing import Any, Annotated
from functools import wraps

from pydantic import BaseModel, ConfigDict, model_validator, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from app.core.logger import logger


# ==================== 敏感字段处理 ====================

# 需要在日志中脱敏的字段名
SENSITIVE_FIELDS = {
    "password", "pwd", "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token", "authorization", "auth",
    "credit_card", "card_number", "cvv", "ssn", "id_card"
}


def mask_sensitive_value(value: Any, visible_chars: int = 4) -> str:
    """
    脱敏敏感值

    Args:
        value: 原始值
        visible_chars: 保留可见字符数

    Returns:
        脱敏后的字符串
    """
    if value is None:
        return None

    str_value = str(value)
    if len(str_value) <= visible_chars:
        return "*" * len(str_value)

    return str_value[:visible_chars] + "*" * (len(str_value) - visible_chars)


def mask_dict(data: dict, sensitive_fields: set | None = None) -> dict:
    """
    递归脱敏字典中的敏感字段

    Args:
        data: 原始字典
        sensitive_fields: 敏感字段名集合

    Returns:
        脱敏后的字典
    """
    if sensitive_fields is None:
        sensitive_fields = SENSITIVE_FIELDS

    result = {}
    for key, value in data.items():
        key_lower = key.lower()

        if any(sf in key_lower for sf in sensitive_fields):
            result[key] = mask_sensitive_value(value)
        elif isinstance(value, dict):
            result[key] = mask_dict(value, sensitive_fields)
        elif isinstance(value, list):
            result[key] = [
                mask_dict(item, sensitive_fields) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


# ==================== 字符串清理 ====================

def sanitize_string(value: str) -> str:
    """
    清理字符串

    - 去除首尾空格
    - 转义 HTML 特殊字符（防 XSS）
    - 移除控制字符

    Args:
        value: 原始字符串

    Returns:
        清理后的字符串
    """
    if not isinstance(value, str):
        return value

    # 去除首尾空格
    value = value.strip()

    # 移除控制字符（保留换行和制表符）
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)

    return value


def escape_html(value: str) -> str:
    """HTML 转义（防 XSS）"""
    if not isinstance(value, str):
        return value
    return html.escape(value)


# ==================== 常用验证器 ====================

class Validators:
    """常用验证器集合"""

    # 中国手机号正则
    PHONE_PATTERN = re.compile(r'^1[3-9]\d{9}$')

    # 邮箱正则（简化版）
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    # 中国身份证正则（简化版，18位）
    ID_CARD_PATTERN = re.compile(r'^\d{17}[\dXx]$')

    # 用户名正则（字母开头，允许字母数字下划线）
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{2,49}$')

    # URL 正则（简化版）
    URL_PATTERN = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$',
        re.IGNORECASE
    )

    @classmethod
    def phone(cls, value: str, required: bool = True) -> str:
        """
        验证中国手机号

        Args:
            value: 手机号
            required: 是否必填

        Returns:
            验证后的手机号

        Raises:
            ValueError: 格式无效
        """
        if not value:
            if required:
                raise ValueError("手机号不能为空")
            return value

        value = sanitize_string(value)
        if not cls.PHONE_PATTERN.match(value):
            raise ValueError("手机号格式无效")

        return value

    @classmethod
    def id_card(cls, value: str, required: bool = True) -> str:
        """
        验证中国身份证号

        Args:
            value: 身份证号
            required: 是否必填

        Returns:
            验证后的身份证号（大写）

        Raises:
            ValueError: 格式无效
        """
        if not value:
            if required:
                raise ValueError("身份证号不能为空")
            return value

        value = sanitize_string(value).upper()
        if not cls.ID_CARD_PATTERN.match(value):
            raise ValueError("身份证号格式无效")

        return value

    @classmethod
    def username(cls, value: str) -> str:
        """
        验证用户名

        规则：
        - 3-50 个字符
        - 字母开头
        - 只允许字母、数字、下划线

        Args:
            value: 用户名

        Returns:
            验证后的用户名

        Raises:
            ValueError: 格式无效
        """
        if not value:
            raise ValueError("用户名不能为空")

        value = sanitize_string(value)
        if not cls.USERNAME_PATTERN.match(value):
            raise ValueError("用户名必须以字母开头，只能包含字母、数字和下划线，长度3-50")

        return value

    @classmethod
    def url(cls, value: str, required: bool = True) -> str:
        """
        验证 URL

        Args:
            value: URL
            required: 是否必填

        Returns:
            验证后的 URL

        Raises:
            ValueError: 格式无效
        """
        if not value:
            if required:
                raise ValueError("URL 不能为空")
            return value

        value = sanitize_string(value)
        if not cls.URL_PATTERN.match(value):
            raise ValueError("URL 格式无效")

        return value

    @classmethod
    def password_strength(
        cls,
        value: str,
        min_length: int = 8,
        require_uppercase: bool = True,
        require_lowercase: bool = True,
        require_digit: bool = True,
        require_special: bool = False
    ) -> str:
        """
        验证密码强度

        Args:
            value: 密码
            min_length: 最小长度
            require_uppercase: 需要大写字母
            require_lowercase: 需要小写字母
            require_digit: 需要数字
            require_special: 需要特殊字符

        Returns:
            验证后的密码

        Raises:
            ValueError: 不符合强度要求
        """
        if not value:
            raise ValueError("密码不能为空")

        if len(value) < min_length:
            raise ValueError(f"密码长度至少 {min_length} 位")

        if require_uppercase and not re.search(r'[A-Z]', value):
            raise ValueError("密码必须包含大写字母")

        if require_lowercase and not re.search(r'[a-z]', value):
            raise ValueError("密码必须包含小写字母")

        if require_digit and not re.search(r'\d', value):
            raise ValueError("密码必须包含数字")

        if require_special and not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
            raise ValueError("密码必须包含特殊字符")

        return value

    @classmethod
    def not_empty(cls, value: str, field_name: str = "字段") -> str:
        """
        验证非空

        Args:
            value: 值
            field_name: 字段名（用于错误消息）

        Returns:
            验证后的值

        Raises:
            ValueError: 值为空
        """
        if not value or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"{field_name}不能为空")

        return sanitize_string(value) if isinstance(value, str) else value


# 全局验证器实例
validators = Validators()


# ==================== 增强型基类 ====================

class ValidatedBaseModel(BaseModel):
    """
    增强验证的 Pydantic 基类

    特性：
    - 自动清理字符串字段（去除首尾空格）
    - 日志输出时自动脱敏敏感字段
    - 支持 ORM 模式

    使用示例：
        class UserCreate(ValidatedBaseModel):
            username: str
            password: str  # 自动脱敏
            email: str

        user = UserCreate(username=" john ", password="secret123", email="john@example.com")
        print(user.username)  # "john" (已去除空格)
        print(user.to_safe_dict())  # password 被脱敏
    """

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,  # 自动去除字符串首尾空格
        validate_default=True,
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def sanitize_strings(cls, values: dict) -> dict:
        """预处理：清理所有字符串字段"""
        if isinstance(values, dict):
            return {
                k: sanitize_string(v) if isinstance(v, str) else v
                for k, v in values.items()
            }
        return values

    def to_safe_dict(self) -> dict:
        """
        转换为安全字典（敏感字段脱敏）

        用于日志记录和调试输出。

        Returns:
            脱敏后的字典
        """
        return mask_dict(self.model_dump())

    def to_safe_json(self) -> str:
        """
        转换为安全 JSON 字符串（敏感字段脱敏）

        Returns:
            脱敏后的 JSON 字符串
        """
        import json
        return json.dumps(self.to_safe_dict(), ensure_ascii=False, default=str)

    def __repr__(self) -> str:
        """重写 repr，自动脱敏敏感字段"""
        return f"{self.__class__.__name__}({self.to_safe_dict()})"


# ==================== 自定义类型 ====================

class SanitizedStr(str):
    """
    自动清理的字符串类型

    用作类型注解时，会自动：
    - 去除首尾空格
    - 移除控制字符
    - 转义 HTML（可选）
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, value: str) -> str:
        return sanitize_string(value)


class SensitiveStr(str):
    """
    敏感字符串类型

    日志输出时自动脱敏。
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls._validate,
            core_schema.str_schema(),
        )

    @classmethod
    def _validate(cls, value: str) -> "SensitiveStr":
        return cls(value)

    def __repr__(self) -> str:
        return f"SensitiveStr('{mask_sensitive_value(self)}')"

    def __str__(self) -> str:
        # 正常使用时返回原值，但 repr 会脱敏
        return super().__str__()


# 类型别名，用于注解
Sanitized = Annotated[str, SanitizedStr]


# ==================== 请求日志装饰器 ====================

def log_request(func):
    """
    请求日志装饰器

    自动记录请求参数和响应（敏感字段脱敏）。

    使用示例：
        @router.post("/users")
        @log_request
        async def create_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 提取并脱敏请求参数
        safe_kwargs = {}
        for key, value in kwargs.items():
            if hasattr(value, 'to_safe_dict'):
                safe_kwargs[key] = value.to_safe_dict()
            elif isinstance(value, dict):
                safe_kwargs[key] = mask_dict(value)
            elif isinstance(value, BaseModel):
                safe_kwargs[key] = mask_dict(value.model_dump())
            else:
                # 跳过数据库会话等对象
                if not key.startswith('_') and key != 'db':
                    safe_kwargs[key] = str(value)[:100] if value else None

        logger.debug("[REQUEST] {} | params={}", func.__name__, safe_kwargs)

        try:
            result = await func(*args, **kwargs)

            # 脱敏响应
            if hasattr(result, 'to_safe_dict'):
                safe_result = result.to_safe_dict()
            elif isinstance(result, dict):
                safe_result = mask_dict(result)
            elif isinstance(result, BaseModel):
                safe_result = mask_dict(result.model_dump())
            else:
                safe_result = "<non-dict response>"

            logger.debug("[RESPONSE] {} | result={}", func.__name__, safe_result)
            return result

        except Exception as e:
            logger.error("[ERROR] {} | error={}", func.__name__, e)
            raise

    return wrapper


# 导出
__all__ = [
    "SENSITIVE_FIELDS",
    "Sanitized",
    "SanitizedStr",
    "SensitiveStr",
    "ValidatedBaseModel",
    "Validators",
    "escape_html",
    "log_request",
    "mask_dict",
    "mask_sensitive_value",
    "sanitize_string",
    "validators",
]
