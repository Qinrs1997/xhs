"""搜索历史端点

端点列表：
- GET    /search/history              - 搜索历史列表
- GET    /search/history/{id}         - 搜索历史详情
- DELETE /search/history/{id}         - 删除搜索历史
- GET    /search/history/{id}/status  - 搜索生成进度
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.core.exceptions import NotFoundError, InternalError
from app.core.database import get_async_db
from app.models.user import User
from app.core.logger import logger
from app.crud.search_history import search_history_crud
from app.schemas.search_history import SearchHistoryItem, SearchHistoryDetail, SearchHistoryStatusResponse
from app.schemas.response import Response, PaginatedData

router = APIRouter()


# ==================== 搜索历史端点 ====================


@router.get(
    "/search/history",
    response_model=Response[PaginatedData[SearchHistoryItem]],
    summary="搜索历史列表",
    description="获取当前用户的搜索历史记录列表，支持关键词和状态过滤",
)
async def list_search_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词过滤"),
    status: Optional[str] = Query(None, description="状态过滤: completed/generating/failed"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取当前用户的搜索历史记录列表"""
    try:
        items, total = await search_history_crud.get_list_by_user(
            db,
            user_id=current_user.id,
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
        )

        # 组装列表项（从 eager load 的关系中直接取 task_id，避免 N+1 查询）
        result_items = []
        for item in items:
            task_ids = [link.task_id for link in (item.generated_task_links or [])]
            result_items.append(SearchHistoryItem(
                id=item.id,
                query=item.query,
                summary=item.summary,
                sources_count=item.sources_count,
                status=item.status,
                generated_tasks_count=len(task_ids),
                generated_task_ids=task_ids,
                created_at=item.created_at,
                metadata_info=item.metadata_info,
            ))

        paginated = PaginatedData.create(
            items=result_items,
            total=total,
            page=page,
            page_size=page_size,
        )
        return Response(data=paginated)
    except Exception as e:
        logger.exception("获取搜索历史列表异常: {}", e)
        raise InternalError("获取搜索历史列表失败") from e


@router.get(
    "/search/history/{history_id}",
    response_model=Response[SearchHistoryDetail],
    summary="搜索历史详情",
    description="获取单条搜索历史的完整信息，包含关联任务列表",
)
async def get_search_history_detail(
    history_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取搜索历史详情"""
    try:
        item = await search_history_crud.get_detail(
            db, id=history_id, user_id=current_user.id,
        )
        if not item:
            raise NotFoundError("搜索记录不存在")

        # 获取关联任务的详细信息
        task_ids = []
        generated_tasks = []
        for link in (item.generated_task_links or []):
            task_ids.append(link.task_id)

        # 批量查询关联任务的简要信息
        if task_ids:
            from app.crud.xhs_task import xhs_task
            from app.schemas.search_history import GeneratedTaskBrief
            tasks = await xhs_task.get_by_ids(db, ids=task_ids)
            generated_tasks = [
                GeneratedTaskBrief(
                    id=t.id,
                    title=t.title,
                    status=t.status.value if hasattr(t.status, 'value') else str(t.status),
                    created_at=t.created_at,
                )
                for t in tasks
            ]

        detail = SearchHistoryDetail(
            id=item.id,
            query=item.query,
            summary=item.summary,
            full_summary=item.full_summary,
            sources_count=item.sources_count,
            status=item.status,
            results=item.search_results,
            generated_tasks_count=len(task_ids),
            generated_task_ids=task_ids,
            generated_tasks=generated_tasks,
            created_at=item.created_at,
            metadata_info=item.metadata_info,
        )
        return Response(data=detail)
    except NotFoundError:
        raise
    except Exception as e:
        logger.exception("获取搜索历史详情异常: {}", e)
        raise InternalError("获取搜索历史详情失败") from e


@router.delete(
    "/search/history/{history_id}",
    response_model=Response[dict],
    summary="删除搜索历史",
    description="删除指定的搜索历史记录（校验用户归属权）",
)
async def delete_search_history(
    history_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """删除搜索历史记录"""
    try:
        deleted = await search_history_crud.delete_by_user(
            db, id=history_id, user_id=current_user.id,
        )
        if not deleted:
            raise NotFoundError("搜索记录不存在")

        return Response(data={"message": "删除成功"})
    except NotFoundError:
        raise
    except Exception as e:
        logger.exception("删除搜索历史异常: {}", e)
        raise InternalError("删除搜索历史失败") from e


@router.get(
    "/search/history/{history_id}/status",
    response_model=Response[SearchHistoryStatusResponse],
    summary="搜索生成进度查询",
    description="查询搜索记录的当前生成进度（用于 SSE 断线重连后查询）",
)
async def get_search_history_status(
    history_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_active_user),
):
    """查询搜索生成进度"""
    try:
        item = await search_history_crud.get_detail(
            db, id=history_id, user_id=current_user.id,
        )
        if not item:
            raise NotFoundError("搜索记录不存在")

        # 根据当前状态构建步骤信息
        from app.schemas.search_history import StepStatus

        if item.status == "completed":
            task_count = len(item.generated_task_links or [])
            steps = [
                StepStatus(name="搜索", status="done"),
                StepStatus(name="AI 总结", status="done"),
                StepStatus(name="选题拆分", status="done"),
                StepStatus(name="文章生成", status="done", progress=f"{task_count}/{task_count}"),
            ]
            status_response = SearchHistoryStatusResponse(
                status="completed",
                progress=100,
                current_step="全部完成",
                steps=steps,
            )
        elif item.status == "failed":
            steps = [
                StepStatus(name="搜索", status="done"),
                StepStatus(name="处理", status="failed"),
            ]
            status_response = SearchHistoryStatusResponse(
                status="failed",
                progress=0,
                current_step="生成失败",
                steps=steps,
            )
        else:
            # generating 状态（需要从元数据中获取更详细的进度，目前返回基本信息）
            steps = [
                StepStatus(name="搜索", status="done"),
                StepStatus(name="处理中", status="running"),
            ]
            status_response = SearchHistoryStatusResponse(
                status="generating",
                progress=50,
                current_step="正在生成中...",
                steps=steps,
            )

        return Response(data=status_response)
    except NotFoundError:
        raise
    except Exception as e:
        logger.exception("查询搜索生成进度异常: {}", e)
        raise InternalError("查询进度失败") from e
