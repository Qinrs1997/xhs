"""AI 搜索 + 总结端点

端点列表：
- POST /summary          - 文本总结
- POST /search           - 联网搜索（支持指定 Provider）
- POST /search/chat      - 联网搜索并回答
- POST /search/stream    - 流式联网搜索 (SSE)
- GET  /search/providers  - 可用搜索引擎列表

已拆分到独立文件：
- ai_image.py        → /image/models, /image/generate
- search_history.py  → /search/history/* (4 个端点)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
import json

from app.api.deps import get_current_active_user
from app.core.exceptions import BadRequestError, ServiceUnavailableError, InternalError
from app.core.rate_limit import rate_limit
from app.core.database import get_async_db
from app.models.user import User
from app.ai.facade import ai
from app.ai.schemas.summary import SummaryRequest, SummaryResponse
from app.ai.schemas.search import SearchRequest, SearchResponse
from app.ai.config import ai_config
from app.ai.exceptions import AIError
from app.core.logger import logger
from app.crud.search_history import search_history_crud
from app.schemas.response import Response

router = APIRouter()


# ==================== 总结端点 ====================


@router.post(
    "/summary",
    response_model=Response[SummaryResponse],
    summary="文本总结",
    description="对长文本进行总结，支持多种总结风格"
)
async def summarize(
    request: SummaryRequest,
    current_user: User = Depends(get_current_active_user),
) -> SummaryResponse:
    """
    文本总结

    - **text**: 要总结的文本
    - **style**: 总结风格 (brief=简洁, detailed=详细, bullet=要点)
    - **max_length**: 总结最大长度
    - **language**: 输出语言 (zh=中文, en=英文)
    """
    if not ai_config.summary_enabled:
        raise ServiceUnavailableError("总结功能未启用")

    if not request.text and not request.conversation_id:
        raise BadRequestError("text 或 conversation_id 必须提供一个")

    try:
        if request.conversation_id:
            return Response(data=await ai.summarize_conversation(
                conversation_id=request.conversation_id,
                style=request.style,
            ))
        else:
            return Response(data=await ai.summarize(
                text=request.text,
                style=request.style,
                max_length=request.max_length,
                language=request.language,
            ))
    except AIError as e:
        logger.error("AI 总结失败: {}", e)
        raise InternalError(e.message) from e
    except ValueError as e:
        raise BadRequestError(str(e)) from e


# ==================== 搜索端点 ====================


def _get_search_rate_limit():
    """从配置读取搜索限流值"""
    rpm = getattr(ai_config.search, "rate_limit_rpm", 20)
    return rate_limit(requests_per_minute=rpm)


@router.get(
    "/search/providers",
    response_model=Response[dict],
    summary="可用搜索引擎列表",
    description="获取所有已注册的搜索引擎及其元信息，用于前端搜索引擎选择器"
)
async def list_search_providers(
    current_user: User = Depends(get_current_active_user),
):
    """
    获取可用搜索引擎列表

    返回每个搜索引擎的名称、描述、是否需要 Key、是否已配置可用、支持的功能等信息。
    前端可据此展示搜索引擎选择器。
    """
    try:
        from app.ai.services.search import SearchService
        providers = SearchService.get_available_providers()
        return Response(data={
            "default": ai_config.search.provider if ai_config.search.enabled else "duckduckgo",
            "providers": providers,
        })
    except Exception as e:
        logger.exception("获取搜索引擎列表异常: {}", e)
        raise InternalError("获取搜索引擎列表失败") from e


@router.post(
    "/search",
    response_model=Response[SearchResponse],
    summary="联网搜索",
    description="搜索网络内容并返回结果，可选 AI 总结，支持指定搜索引擎"
)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
    _: None = Depends(_get_search_rate_limit()),
) -> SearchResponse:
    """
    联网搜索

    - **query**: 搜索查询
    - **max_results**: 最大结果数（默认 5）
    - **include_summary**: 是否包含 AI 生成的总结（默认 True）
    - **search_depth**: 搜索深度 basic/advanced（默认 basic）
    - **provider**: 搜索引擎（可选：duckduckgo/tavily/serper/searxng）

    返回搜索结果列表和可选的 AI 总结。搜索完成后自动保存到搜索历史。
    """
    if not ai_config.search_enabled:
        raise ServiceUnavailableError("搜索功能未启用")

    import time
    search_start = time.time()

    try:
        response = await ai.search(
            query=request.query,
            max_results=request.max_results,
            include_summary=request.include_summary,
            provider=request.provider,
            user_id=current_user.id,
        )

        search_latency = int((time.time() - search_start) * 1000)

        # 自动保存搜索历史（不阻塞搜索响应）
        try:
            from app.schemas.search_history import SearchHistoryCreate

            full_summary = response.summary or ""
            summary = full_summary[:200] if full_summary else ""

            # 构建搜索结果列表（用于详情展示）
            search_results_data = [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "score": r.score,
                }
                for r in response.results
            ]

            # 搜索元数据
            metadata_info = {
                "model": response.metadata.model if response.metadata else None,
                "latency_ms": search_latency,
                "search_provider": request.provider or "default",
                "max_results": request.max_results,
                "include_summary": request.include_summary,
            }

            history_data = SearchHistoryCreate(
                query=request.query,
                summary=summary,
                full_summary=full_summary,
                sources_count=response.sources_used,
                status="completed",
                search_results=search_results_data,
                metadata_info=metadata_info,
            )
            history = await search_history_crud.create_for_user(
                db, obj_in=history_data, user_id=current_user.id,
            )
            # 回填 search_id 到响应，供前端关联后续任务
            response.search_id = history.id
            logger.info("搜索历史已自动保存: query='{}', sources={}, search_id={}", request.query, response.sources_used, history.id)
        except Exception as save_err:
            logger.warning("搜索历史自动保存失败（不影响搜索结果返回）: {}", save_err)

        return Response(data=response)
    except AIError as e:
        logger.error("联网搜索失败: {}", e)
        raise InternalError(e.message) from e
    except Exception as e:
        logger.exception("联网搜索异常: {}", e)
        raise InternalError("搜索服务异常") from e


@router.post(
    "/search/chat",
    response_model=Response[dict],
    summary="联网搜索并回答",
    description="搜索网络内容并用 AI 生成回答，包含引用来源"
)
async def search_and_chat(
    query: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    联网搜索并回答

    搜索网络内容，然后用 AI 根据搜索结果生成回答。
    返回包含引用来源的完整回答。
    """
    if not ai_config.search_enabled:
        raise ServiceUnavailableError("搜索功能未启用")

    try:
        result = await ai.search_and_chat(
            query=query,
            user_id=current_user.id,
        )
        return Response(data=result)
    except AIError as e:
        logger.error("联网搜索回答失败: {}", e)
        raise InternalError(e.message) from e
    except Exception as e:
        logger.exception("联网搜索回答异常: {}", e)
        raise InternalError("搜索服务异常") from e


@router.post(
    "/search/stream",
    summary="流式联网搜索",
    description="先返回搜索来源，再流式返回 AI 回答（SSE），自动保存搜索历史",
    responses={
        200: {
            "description": "SSE 流式响应",
            "content": {
                "text/event-stream": {
                    "example": "event: sources\ndata: [{\"title\": \"...\", \"url\": \"...\"}]\n\nevent: message\ndata: {\"content\": \"...\"}\n\nevent: done\ndata: {}"
                }
            }
        }
    }
)
async def search_stream(
    request: SearchRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    流式联网搜索

    使用 Server-Sent Events 实时返回：
    1. 首先返回搜索到的来源（event: sources）
    2. 然后流式返回 AI 生成的回答（event: message）
    3. 最后返回完成标记（event: done）

    流式完成后自动保存搜索历史记录。
    """
    if not ai_config.search_enabled:
        raise ServiceUnavailableError("搜索功能未启用")

    import time
    search_start = time.time()

    async def event_generator():
        # 收集数据用于保存搜索历史
        collected_sources = []
        collected_content_parts = []
        has_error = False

        try:
            async for event in ai.search_stream(request.query, user_id=current_user.id):
                event_name = event["event"]
                event_data = event["data"]

                # 收集来源
                if event_name == "sources":
                    collected_sources = event_data.get("sources", [])

                # 收集 AI 回答内容
                if event_name == "message":
                    content = event_data.get("content", "")
                    if content:
                        collected_content_parts.append(content)

                yield {
                    "event": event_name,
                    "data": json.dumps(event_data, ensure_ascii=False),
                }
        except AIError as e:
            has_error = True
            logger.error("流式搜索失败: {}", e)
            yield {
                "event": "error",
                "data": json.dumps({"error": e.message}, ensure_ascii=False),
            }
        except Exception as e:
            has_error = True
            logger.exception("流式搜索异常: {}", e)
            yield {
                "event": "error",
                "data": json.dumps({"error": "搜索服务异常"}, ensure_ascii=False),
            }

        # 流结束后保存搜索历史（不阻塞 SSE 响应）
        try:
            from app.schemas.search_history import SearchHistoryCreate

            full_summary = "".join(collected_content_parts)
            summary = full_summary[:200] if full_summary else ""
            elapsed_ms = int((time.time() - search_start) * 1000)

            history_data = SearchHistoryCreate(
                query=request.query,
                summary=summary,
                full_summary=full_summary,
                sources_count=len(collected_sources),
                status="failed" if has_error else "completed",
                search_results=collected_sources,
                metadata_info={
                    "latency_ms": elapsed_ms,
                    "search_provider": request.provider or "default",
                    "max_results": request.max_results,
                    "stream": True,
                },
            )

            # 使用独立的 db session 保存（SSE 中不能用 Depends 注入 session）
            # 仅取第一个 session, break 必须放在 try/except 外,
            # 不能放 finally 里, 否则 finally 的 break 会把 try 内抛出的异常静默吞掉
            async for db in get_async_db():
                await search_history_crud.create_for_user(
                    db, obj_in=history_data, user_id=current_user.id,
                )
                logger.info(
                    "流式搜索历史已保存: query='{}', sources={}, answer_len={}",
                    request.query, len(collected_sources), len(full_summary),
                )
                break
        except Exception as save_err:
            logger.warning("流式搜索历史保存失败(不影响搜索结果): {}", save_err)

    return EventSourceResponse(event_generator())

