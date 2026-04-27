"""提示词管理器 (优化版)

核心管理类，负责加载、缓存、渲染提示词模板。

优化特性：
- 引入 Jinja2 支持 (if/for 等逻辑)
- 全面异步化处理 (anyio)
- 数据库优先逻辑 (DB 覆盖文件)
- 增强的元数据处理
"""
from __future__ import annotations

import re
import anyio
from pathlib import Path
from typing import Optional, List, Dict, Any

import yaml
from jinja2 import Environment, select_autoescape

from app.ai.prompts.models import PromptTemplate, PromptMeta
from app.core.logger import logger

_FRONT_MATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


class PromptManager:
    """提示词管理器 (优化版)"""

    def __init__(
        self,
        templates_dir: str = "app/ai/prompts/templates",
        custom_dir: Optional[str] = "app/ai/prompts/custom",
        cache_enabled: bool = True,
    ):
        self.templates_dir = Path(templates_dir)
        self.custom_dir = Path(custom_dir) if custom_dir else None
        self.cache_enabled = cache_enabled
        self._cache: dict[str, PromptTemplate] = {}

        self.jinja_env = Environment(
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )

        logger.debug("提示词管理器已重载: templates_dir={}, engine=jinja2", templates_dir)

    async def get(
        self,
        key: str,
        variables: Optional[dict] = None,
        fallback: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """异步获取并渲染提示词"""
        template = await self._get_template_async(key, user_id=user_id)

        if not template:
            if fallback:
                logger.warning("提示词 '{}' 未找到，使用降级: {}", key, fallback)
                return await self.get(fallback, variables, user_id=user_id)
            logger.warning("提示词 '{}' 未找到", key)
            return ""

        content = template.content

        # 处理继承 (递归处理)
        if template.meta and template.meta.extends:
            parent_content = await self._resolve_extends_async(template.meta.extends)
            if parent_content:
                content = parent_content + "\n\n" + content

        # 渲染 Jinja2 变量
        if variables or (template.meta and template.meta.variables):
            content = await self._render_jinja2(content, variables, template.meta)

        return content

    async def _get_template_async(self, key: str, user_id: Optional[int] = None) -> Optional[PromptTemplate]:
        """获取模板逻辑：DB 优先 -> 自定义文件 -> 内置文件"""
        cache_key = f"{key}:{user_id}" if user_id else key

        if self.cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        template = None

        # 1. 尝试从数据库加载 (DB 优先，支持动态覆盖)
        template = await self._load_from_db_async(key, user_id)

        # 2. 尝试从自定义文件加载
        if not template and self.custom_dir:
            path = self.custom_dir / f"{key}.md"
            if await anyio.Path(path).exists():
                template = await self._parse_file_async(key, path, source="custom")

        # 3. 从内置文件加载
        if not template:
            path = self.templates_dir / f"{key}.md"
            if await anyio.Path(path).exists():
                template = await self._parse_file_async(key, path, source="file")

        if template and self.cache_enabled:
            self._cache[cache_key] = template

        return template

    async def _load_from_db_async(self, key: str, user_id: Optional[int] = None) -> Optional[PromptTemplate]:
        """异步从数据库查询模板"""
        try:
            # 延迟导入防止循环
            from app.core.database import AsyncSessionLocal
            from sqlalchemy import select
            from app.models.prompt import UserPrompt

            async with AsyncSessionLocal() as session:
                # 优先匹配特定用户的，再匹配公共的（user_id 为 null）
                stmt = select(UserPrompt).where(UserPrompt.key == key)
                if user_id:
                    stmt = stmt.where((UserPrompt.user_id == user_id) | (UserPrompt.user_id.is_(None)))
                else:
                    stmt = stmt.where(
                        (UserPrompt.user_id.is_(None)) | (UserPrompt.is_public.is_(True))
                    )

                stmt = stmt.order_by(UserPrompt.user_id.desc())  # 让用户自己的排在前面

                result = await session.execute(stmt)
                prompt = result.scalars().first()
                if prompt:
                    return self._db_prompt_to_template(prompt)
        except ImportError as e:
            # 导入失败不应静默吞掉，记录错误
            logger.error("DB 提示词加载失败（导入错误）: {}", e)
            return None
        except Exception as e:
            # 如果表还没创建或其他 DB 问题，静默跳过（降级到文件）
            logger.debug("DB 提示词加载跳过: {}", e)
            return None
        return None

    async def _parse_file_async(self, key: str, path: Path, source: str) -> Optional[PromptTemplate]:
        """异步解析 MD 文件"""
        try:
            p = anyio.Path(path)
            content = await p.read_text(encoding="utf-8")

            meta = None
            match = _FRONT_MATTER_RE.match(content)

            if match:
                yaml_str = match.group(1)
                try:
                    meta_dict = yaml.safe_load(yaml_str)
                    if meta_dict:
                        if "id" not in meta_dict: meta_dict["id"] = key
                        meta = PromptMeta(**meta_dict)
                except Exception as e:
                    logger.warning("YAML 解析失败: {} - {}", key, e)
                content = content[match.end():]

            return PromptTemplate(
                key=key,
                content=content.strip(),
                meta=meta,
                source=source
            )
        except Exception as e:
            logger.error("解析模板失败 {}: {}", path, e)
            return None

    async def _resolve_extends_async(self, parents: List[str]) -> str:
        """异步解析继承链"""
        contents = []
        for parent_key in parents:
            parent = await self._get_template_async(parent_key)
            if parent:
                if parent.meta and parent.meta.extends:
                    ancestor = await self._resolve_extends_async(parent.meta.extends)
                    if ancestor: contents.append(ancestor)
                contents.append(parent.content)
        return "\n\n".join(contents)

    async def _render_jinja2(self, content: str, variables: dict, meta: Optional[PromptMeta]) -> str:
        """使用 Jinja2 渲染变量"""
        final_vars = {}
        # 合并默认值
        if meta and meta.variables:
            for k, v in meta.variables.items():
                if isinstance(v, dict) and "default" in v:
                    final_vars[k] = v["default"]

        if variables:
            final_vars.update(variables)

        try:
            template = self.jinja_env.from_string(content)
            # 使用 lambda 包装以支持关键字参数，或者直接在当前线程渲染（Jinja2 渲染通常很快）
            return template.render(**final_vars)
        except Exception as e:
            logger.error("Jinja2 渲染报错: {}", e)
            return content # 降级返回原文

    def _db_prompt_to_template(self, prompt: Any) -> PromptTemplate:
        """DB Result -> Template Object

        注意:`extends` 字段必须映射到 `PromptMeta.extends`,否则 `get()` 的继承链
        解析(见 `_resolve_extends_async`)拿不到父模板 content,DB 模板的继承功能
        就会静默失效。
        """
        raw_extends = getattr(prompt, "extends", None) or []
        extends_list: list[str] = []
        if isinstance(raw_extends, str):
            extends_list = [raw_extends]
        elif isinstance(raw_extends, (list, tuple)):
            extends_list = [str(e) for e in raw_extends if e]
        meta = PromptMeta(
            id=prompt.key,
            name=prompt.name or prompt.key,
            version=getattr(prompt, "version", "1.0.0"),
            variables=getattr(prompt, "variables", {}) or {},
            extends=extends_list,
        )
        return PromptTemplate(
            key=prompt.key,
            content=prompt.content,
            meta=meta,
            source="database",
        )

    async def exists_async(self, key: str, user_id: Optional[int] = None) -> bool:
        """存在性检查:文件 + DB 可见性(与 `get` 语义一致)

        旧的同步 `exists()` 只看文件,会把"仅存在于 DB 的模板"误判为不存在。
        """
        if self.cache_enabled and (f"{key}:{user_id}" in self._cache or key in self._cache):
            return True
        if self.custom_dir:
            path = self.custom_dir / f"{key}.md"
            if await anyio.Path(path).exists():
                return True
        path = self.templates_dir / f"{key}.md"
        if await anyio.Path(path).exists():
            return True
        db_template = await self._load_from_db_async(key, user_id)
        return db_template is not None

    def invalidate(self, key: str, user_id: Optional[int] = None) -> None:
        """按 key(+user_id) 精确淘汰缓存,供 CRUD update/delete 后调用"""
        if not self.cache_enabled:
            return
        if user_id is not None:
            self._cache.pop(f"{key}:{user_id}", None)
        # key 自身的缓存(非 user 维度)也一并清理,避免其他用户拿到旧公共模板快照
        self._cache.pop(key, None)
        # 以及所有 `{key}:{*}` 维度的缓存
        stale = [ck for ck in self._cache if ck.startswith(f"{key}:")]
        for ck in stale:
            self._cache.pop(ck, None)

    # 保留部分兼容同步方法 (加警告)
    def list(self, prefix: Optional[str] = None) -> List[str]:
        # 此处搜索文件系统由于是初始化/展示用，暂时保留同步
        templates = []
        search_dir = self.templates_dir
        if prefix: search_dir = search_dir / prefix
        if search_dir.exists():
            for path in search_dir.rglob("*.md"):
                if path.name.startswith("_"): continue
                key = str(path.relative_to(self.templates_dir)).replace("\\", "/").rsplit(".", 1)[0]
                templates.append(key)
        return sorted(templates)

    def list_with_meta(self, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取提示词列表，包含元数据信息"""
        templates = []
        search_dir = self.templates_dir
        if prefix:
            search_dir = search_dir / prefix

        if search_dir.exists():
            for path in search_dir.rglob("*.md"):
                if path.name.startswith("_"):
                    continue

                key = str(path.relative_to(self.templates_dir)).replace("\\", "/").rsplit(".", 1)[0]

                # 解析文件获取元数据
                meta = {}
                try:
                    content = path.read_text(encoding="utf-8")
                    match = _FRONT_MATTER_RE.match(content)
                    if match:
                        yaml_str = match.group(1)
                        meta = yaml.safe_load(yaml_str) or {}
                except Exception as e:
                    logger.warning("解析提示词元数据失败: {} - {}", key, e)

                templates.append({
                    "key": key,
                    "meta": meta
                })

        # 按 key 排序
        return sorted(templates, key=lambda x: x["key"])

    def get_template(self, key: str) -> Optional[PromptTemplate]:
        """同步获取模板（用于展示目的，不推荐在请求中使用）"""
        # 检查缓存
        if self.cache_enabled and key in self._cache:
            return self._cache[key]

        # 尝试从自定义目录加载
        if self.custom_dir:
            path = self.custom_dir / f"{key}.md"
            if path.exists():
                return self._parse_file_sync(key, path, "custom")

        # 从内置目录加载
        path = self.templates_dir / f"{key}.md"
        if path.exists():
            return self._parse_file_sync(key, path, "file")

        return None

    def _parse_file_sync(self, key: str, path: Path, source: str) -> Optional[PromptTemplate]:
        """同步解析 MD 文件"""
        try:
            content = path.read_text(encoding="utf-8")

            meta = None
            match = _FRONT_MATTER_RE.match(content)

            if match:
                yaml_str = match.group(1)
                try:
                    meta_dict = yaml.safe_load(yaml_str)
                    if meta_dict:
                        if "id" not in meta_dict:
                            meta_dict["id"] = key
                        meta = PromptMeta(**meta_dict)
                except Exception as e:
                    logger.warning("YAML 解析失败: {} - {}", key, e)
                content = content[match.end():]

            template = PromptTemplate(
                key=key,
                content=content.strip(),
                meta=meta,
                source=source
            )

            # 缓存
            if self.cache_enabled:
                self._cache[key] = template

            return template
        except Exception as e:
            logger.error("解析模板失败 {}: {}", path, e)
            return None

    def exists(self, key: str) -> bool:
        """检查提示词是否存在"""
        # 检查缓存
        if self.cache_enabled and key in self._cache:
            return True

        # 检查自定义目录
        if self.custom_dir:
            path = self.custom_dir / f"{key}.md"
            if path.exists():
                return True

        # 检查内置目录
        path = self.templates_dir / f"{key}.md"
        return path.exists()

    def reload(self) -> None:
        self._cache.clear()
        logger.info("Prompt cache reloaded")

# 全局单例
_prompt_manager: Optional[PromptManager] = None

def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

prompts = get_prompt_manager()
