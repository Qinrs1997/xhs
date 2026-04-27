"""XHS 大纲生成接口

POST /outline —— 根据话题 + 参考图 生成小红书图文大纲,
生成成功后自动创建 draft 任务并返回 task_id。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.xhs.outline import XHSOutlineService
from app.ai.services.xhs.schemas import XHSOutlineRequest
from app.api.deps import get_current_active_user
from app.api.v1.endpoints.xhs_helpers import (
    deduct_xhs_credits,
    ensure_xhs_credits,
    get_xhs_credit_cost,
    raise_xhs_error,
    require_xhs_enabled,
)
from app.core.database import get_async_db
from app.core.logger import logger
from app.crud.xhs_task import xhs_task
from app.crud.xhs_template import xhs_template as xhs_template_crud
from app.models.user import User
from app.schemas.response import Response

router = APIRouter()
_outline_service = XHSOutlineService()


def _page_to_task_dict(p) -> dict:
    """序列化大纲 page 为持久化到 DB 的 dict（用于 XHSTaskCreate.pages）"""
    return {
        "page_num": p.page_num if hasattr(p, "page_num") else p.index + 1,
        "content": p.content,
        "page_type": p.page_type,
        "title": p.title,
        "image_prompt": p.image_prompt,
    }


def _page_to_response_dict(p) -> dict:
    """序列化大纲 page 为返给前端的 dict（比 task 版本多 `index`）"""
    return {
        "index": p.index,
        "page_num": p.index + 1,
        "content": p.content,
        "page_type": p.page_type,
        "title": p.title,
        "image_prompt": p.image_prompt,
    }


def _derive_task_title(topic: str) -> str:
    """从 topic 提取 task title（取第一行，最多 200 字符）"""
    raw = topic.split("\n")[0].strip()
    return (raw[:200] if len(raw) > 200 else raw) or topic[:200]


async def _maybe_link_search_history(
    db: AsyncSession, search_id: int, task_id: int, user_id: int
) -> None:
    """如果请求带 search_id，尝试把该任务与搜索记录建立关联（失败不阻断）"""
    try:
        from app.crud.search_history import search_history_crud
        await search_history_crud.link_task_if_not_exists(
            db,
            search_history_id=search_id,
            task_id=task_id,
            user_id=user_id,
        )
    except Exception as link_err:
        logger.warning("大纲创建时关联搜索记录失败: {}", link_err)


async def _create_draft_task(
    db: AsyncSession, request: XHSOutlineRequest, result, user_id: int
) -> tuple[str | None, bool]:
    """生成大纲后自动创建 draft 任务 + 可选关联搜索记录

    失败不阻断大纲返回（返回 (None, False) 由调用方照常返回大纲）。
    """
    try:
        from app.schemas.xhs_task import XHSTaskCreate

        task_data = XHSTaskCreate(
            title=_derive_task_title(request.topic),
            topic=request.topic,
            status="draft",
            template_id=request.template_id,
            pages=[_page_to_task_dict(p) for p in result.pages],
        )
        task = await xhs_task.create_for_user(db, obj_in=task_data, user_id=user_id)

        if request.search_id:
            await _maybe_link_search_history(db, request.search_id, task.id, user_id)

        return str(task.id), True
    except Exception as te:
        logger.warning("自动创建任务失败（不影响大纲返回）: {}", te)
        return None, False


def _render_content_prompt(tpl_str: str, ctx: dict) -> str:
    """把模板正文级 prompt 用 Jinja2 渲染。渲染失败则回退为原文，确保不阻断大纲流程。"""
    if not tpl_str:
        return ""
    try:
        from jinja2 import Environment, StrictUndefined, UndefinedError
        env = Environment(
            autoescape=False,
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        return env.from_string(tpl_str).render(**ctx).strip()
    except UndefinedError as ue:
        logger.warning("content_prompt_template 渲染变量缺失: {}", ue)
        return tpl_str.strip()
    except Exception as e:
        logger.warning("content_prompt_template 渲染失败: {}", e)
        return tpl_str.strip()


def _merge_template_text(template_text: str, request_text: str) -> str:
    template_text = (template_text or "").strip()
    request_text = (request_text or "").strip()
    if not template_text:
        return request_text
    if not request_text:
        return template_text
    if template_text in request_text:
        return request_text
    if request_text in template_text:
        return template_text
    return f"{template_text}\n\n{request_text}"


async def _maybe_build_search_context(
    db: AsyncSession, search_id: int, user_id: int, max_snippets: int = 5
) -> str:
    """如果前端指示要用搜索上下文，从 search_history 里取摘要/片段拼成字符串。

    失败、无记录或未开启都返回空串，不阻断大纲生成。
    """
    try:
        from app.crud.search_history import search_history_crud
        record = await search_history_crud.get_detail(
            db, id=search_id, user_id=user_id
        )
    except Exception as e:
        logger.warning("读取搜索历史失败 (search_id={}): {}", search_id, e)
        return ""

    if record is None:
        return ""

    lines: list[str] = []
    summary = record.full_summary or record.summary
    if summary:
        lines.append(f"- 摘要: {str(summary).strip()[:600]}")

    results = record.search_results
    # search_results 可能是 list[dict] 或 {"items":[...]} 之类
    if isinstance(results, dict):
        results = results.get("items") or results.get("results") or []
    if isinstance(results, list):
        for r in results[:max_snippets]:
            if not isinstance(r, dict):
                continue
            title = str(r.get("title", "")).strip()
            snippet = str(
                r.get("snippet") or r.get("content") or r.get("description") or ""
            ).strip()
            if title or snippet:
                lines.append(f"- {title[:80]}: {snippet[:240]}")

    return "\n".join(lines).strip()


async def _merge_template_defaults(
    db: AsyncSession, request: XHSOutlineRequest
) -> XHSOutlineRequest:
    """若 request.template_id 有效,把模板里的 `style_prompt`/`content_prompt_template`/`page_count` 注入。

    合并策略:
    - `request.style_prompt` 为空时回填 `template.style_prompt`
    - `request.style_prompt` 非空时拼接 `"{template.style_prompt}\n\n{request.style_prompt}"`,
      允许用户在模板风格基础上追加个性化要求
    - `request.page_count` 为空/0 时回填 `template.page_count`
    - `content_prompt_template` 按 Jinja 渲染({topic}/{keywords})后写入 `request.content_prompt`
      （仅在 request.content_prompt 为空时才回填，前端可显式覆盖）
    - 模板已下架(`is_active=False`)会被 get_by_id 过滤,不参与合并
    """
    if not request.template_id:
        return request
    tpl = await xhs_template_crud.get_by_id(db, template_id=request.template_id)
    if tpl is None:
        return request

    # copy request 保证调用方数据不被意外改写(保持前端侧的可追溯性)
    merged = request.model_copy()
    tpl_style = (tpl.style_prompt or "").strip()
    tpl_page_count = tpl.page_count or 0

    if tpl_style:
        merged.style_prompt = _merge_template_text(tpl_style, merged.style_prompt or "")

    tpl_content_prompt = (getattr(tpl, "content_prompt_template", None) or "").strip()
    if tpl_content_prompt and not (merged.content_prompt or "").strip():
        rendered = _render_content_prompt(
            tpl_content_prompt,
            {
                "topic": merged.topic or "",
                "keywords": merged.topic or "",
                "tone": merged.tone or "",
                "language": merged.language or "zh",
                "page_count": merged.page_count or tpl_page_count,
            },
        )
        if rendered:
            merged.content_prompt = rendered

    if (not merged.page_count or merged.page_count <= 0) and tpl_page_count > 0:
        merged.page_count = tpl_page_count

    return merged


@router.post("/outline", dependencies=[Depends(require_xhs_enabled)])
async def generate_outline(
    request: XHSOutlineRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """生成小红书大纲(自动创建 draft 任务并返回 task_id)"""
    try:
        # 按 template_id 注入默认 style/content_prompt/page_count,前端无需重复传
        request = await _merge_template_defaults(db, request)
        logger.info(
            "/xhs/outline received: user={}, template_id={}, page_count={}, "
            "style_prompt_len={}, content_prompt_len={}, search_id={}, search_context_len={}",
            current_user.id,
            request.template_id,
            request.page_count,
            len(request.style_prompt or ""),
            len(request.content_prompt or ""),
            request.search_id,
            len(request.search_context or ""),
        )

        credit_cost = get_xhs_credit_cost("outline")
        await ensure_xhs_credits(db, current_user.id, credit_cost)

        # 如前端显式请求用搜索上下文,从 search_history 拉摘要拼入
        search_context = (request.search_context or "").strip()
        if len(search_context) > 6000:
            search_context = search_context[:6000]
        if not search_context and request.search_id and request.use_search_context:
            search_context = await _maybe_build_search_context(
                db, request.search_id, current_user.id
            )

        result = await _outline_service.generate_outline(
            topic=request.topic,
            images=request.images,
            style_prompt=request.style_prompt,
            page_count=request.page_count,
            tone=request.tone,
            language=request.language,
            user_id=current_user.id,
            content_prompt=request.content_prompt,
            search_context=search_context or None,
        )

        task_id, task_created = await _create_draft_task(
            db, request, result, current_user.id
        )

        # 大纲成功创建 draft 任务 → 视为"首次应用模板",原子递增 use_count
        # (save 路径单独处理另一类"用户手动保存"的计数,逻辑互不干扰)
        if task_created and request.template_id:
            try:
                await xhs_template_crud.increment_use_count(
                    db, template_id=request.template_id
                )
            except Exception as inc_err:
                logger.warning("模板使用计数递增失败(不影响大纲): {}", inc_err)

        await deduct_xhs_credits(
            db,
            current_user.id,
            credit_cost,
            transaction_type="usage_outline",
            description="XHS outline generation",
            reference_id=task_id,
        )
        await db.commit()

        return Response(
            code=200,
            success=True,
            message="大纲生成成功",
            data={
                "task_id": task_id,
                "task_created": task_created,
                "outline": result.outline,
                "pages": [_page_to_response_dict(p) for p in result.pages],
            },
        )
    except Exception as e:
        logger.exception("XHS 大纲生成失败: {}", e)
        raise_xhs_error(e, "大纲生成")
