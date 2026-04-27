"""XHS 批量搜索生成 API

接口列表：
- POST /generate/batch-from-search         一键批量生成
- POST /generate/batch-from-search/stream   SSE 流式批量生成
"""
import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_active_user
from app.models.user import User
from app.ai.services.xhs.schemas import BatchFromSearchRequest, BatchFromSearchResponse
from app.ai.services.xhs.batch_generator import batch_generator_service
from app.schemas.response import Response
from app.core.logger import logger
from app.core.database import get_async_db
from app.api.v1.endpoints.xhs_helpers import require_xhs_enabled, raise_xhs_error

router = APIRouter()


@router.post("/generate/batch-from-search",
             response_model=Response[BatchFromSearchResponse],
             summary="搜索→拆分→批量生成图文（一键）",
             dependencies=[Depends(require_xhs_enabled)])
async def generate_batch_from_search(
    request: BatchFromSearchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
) -> Any:
    """一键从搜索到批量生成小红书图文"""
    try:
        result = await batch_generator_service.generate_batch(
            topic=request.topic,
            count=request.count,
            style=request.style or "casual",
            search_provider=request.search_provider,
            max_search_results=request.max_search_results,
            copy_length=request.copy_length or "medium",
            include_emoji=request.include_emoji if request.include_emoji is not None else True,
            user_id=current_user.id,
            db=db,
        )

        if request.search_history_id and result.success > 0:
            try:
                from app.crud.search_history import search_history_crud
                success_task_ids = [t.task_id for t in result.tasks if t.task_id and t.status == "success"]
                if success_task_ids:
                    await search_history_crud.add_generated_tasks_batch(
                        db,
                        search_history_id=request.search_history_id,
                        task_ids=success_task_ids,
                    )
                    logger.info(
                        "批量生成: 已关联 {} 个任务到搜索记录 {}",
                        len(success_task_ids), request.search_history_id,
                    )
            except Exception as link_err:
                logger.warning("批量生成: 关联搜索记录失败（不影响结果返回）: {}", link_err)

        return Response(
            code=200,
            success=True,
            message=f"批量生成完成：成功 {result.success} 条，失败 {result.failed} 条",
            data=result,
        )
    except Exception as e:
        logger.exception("批量搜索生成失败: {}", e)
        raise_xhs_error(e, "批量搜索生成")


@router.post("/generate/batch-from-search/stream",
             summary="搜索→拆分→批量生成图文（SSE 流式）",
             dependencies=[Depends(require_xhs_enabled)])
async def generate_batch_from_search_stream(
    request: BatchFromSearchRequest,
    raw_request: Request = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """SSE 流式批量搜索生成"""
    async def event_generator():
        import time as _time
        stream_start = _time.time()

        try:
            async for event in batch_generator_service.generate_batch_stream(
                topic=request.topic,
                count=request.count,
                style=request.style or "casual",
                search_provider=request.search_provider,
                max_search_results=request.max_search_results,
                copy_length=request.copy_length or "medium",
                include_emoji=request.include_emoji if request.include_emoji is not None else True,
                user_id=current_user.id,
                db=db,
            ):
                if raw_request and await raw_request.is_disconnected():
                    logger.info("批量生成 SSE 客户端已断开")
                    yield {
                        "event": "done",
                        "data": json.dumps({"message": "客户端已断开"}, ensure_ascii=False),
                    }
                    return

                event_data = event["data"]
                event_name = event["event"]
                elapsed_ms = int((_time.time() - stream_start) * 1000)

                step_map = {
                    "search_done": "搜索",
                    "split_done": "选题拆分",
                    "progress": "文章生成",
                    "done": "完成",
                }
                if event_name in step_map:
                    event_data["step"] = step_map[event_name]
                    event_data["duration_ms"] = elapsed_ms

                if event_name == "done" and request.search_history_id:
                    try:
                        from app.crud.search_history import search_history_crud
                        tasks_data = event_data.get("tasks", [])
                        success_task_ids = [
                            t.get("task_id") or t.task_id
                            for t in tasks_data
                            if (t.get("task_id") or getattr(t, "task_id", None))
                            and (t.get("status") or getattr(t, "status", None)) == "success"
                        ]
                        if success_task_ids:
                            await search_history_crud.add_generated_tasks_batch(
                                db,
                                search_history_id=request.search_history_id,
                                task_ids=success_task_ids,
                            )
                            logger.info(
                                "SSE 批量生成: 已关联 {} 个任务到搜索记录 {}",
                                len(success_task_ids), request.search_history_id,
                            )
                    except Exception as link_err:
                        logger.warning("SSE 批量生成: 关联搜索记录失败: {}", link_err)

                yield {
                    "event": event_name,
                    "data": json.dumps(event_data, ensure_ascii=False),
                }
        except asyncio.CancelledError:
            logger.info("批量生成 SSE 流已取消")
        except Exception as e:
            logger.exception("批量生成 SSE 流异常: {}", e)
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())
