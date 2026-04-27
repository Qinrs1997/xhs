"""提示词管理模块

企业级提示词管理系统，支持：
- 文件化存储（.md 格式）
- 模板继承
- 变量渲染
- 元数据管理
- 缓存 + 热加载

使用方式：
    from app.ai.prompts import prompts

    # 获取提示词
    prompt = prompts.get("chat/default")

    # 带变量渲染
    prompt = prompts.get("roles/business/customer_service", variables={
        "company_name": "ABC科技",
    })

    # 获取元数据
    meta = prompts.get_meta("roles/business/customer_service")

    # 列出所有可用模板
    templates = prompts.list("roles")
"""
from app.ai.prompts.manager import PromptManager, get_prompt_manager, prompts
from app.ai.prompts.models import PromptTemplate, PromptMeta

__all__ = [
    "PromptManager",
    "PromptMeta",
    "PromptTemplate",
    "get_prompt_manager",
    "prompts",
]
