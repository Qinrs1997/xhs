"""提示词数据模型"""
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class VariableConfig:
    """变量配置"""
    type: str = "string"
    required: bool = False
    default: Optional[str] = None
    description: str = ""
    example: Optional[str] = None


@dataclass
class PromptMeta:
    """提示词元数据

    从 YAML Front Matter 解析，用于描述提示词的属性。
    """
    id: str = ""                              # 唯一标识
    name: str = ""                            # 显示名称
    version: str = "1.0.0"                    # 版本号
    description: str = ""                     # 描述
    author: str = ""                          # 作者
    created_at: Optional[str] = None          # 创建时间
    updated_at: Optional[str] = None          # 更新时间
    extends: list[str] = field(default_factory=list)  # 继承的模板
    variables: dict[str, Any] = field(default_factory=dict)  # 变量定义
    tags: list[str] = field(default_factory=list)     # 标签

    def get_variable_default(self, name: str) -> Optional[str]:
        """获取变量默认值"""
        if name in self.variables:
            var_config = self.variables[name]
            if isinstance(var_config, dict):
                return var_config.get("default")
        return None

    def get_required_variables(self) -> list[str]:
        """获取必填变量列表"""
        required = []
        for name, config in self.variables.items():
            if isinstance(config, dict) and config.get("required", False):
                required.append(name)
        return required

    def to_dict(self) -> dict:
        """转换为字典（用于 API 返回）"""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "variables": list(self.variables.keys()) if self.variables else [],
        }


@dataclass
class PromptTemplate:
    """提示词模板

    包含提示词内容和元数据。
    """
    key: str                                  # 模板路径，如 "roles/business/customer_service"
    content: str                              # 提示词内容
    meta: Optional[PromptMeta] = None         # 元数据
    source: str = "file"                      # 来源：file, custom, database

    def render(self, variables: dict | None = None) -> str:
        """渲染模板变量"""
        if not variables:
            return self.content

        result = self.content
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "key": self.key,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "meta": self.meta.to_dict() if self.meta else None,
            "source": self.source,
        }
