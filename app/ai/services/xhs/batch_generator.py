"""批量搜索生成编排服务

编排 搜索 + TopicSplitter + XHSContentService + 任务创建 的完整流程。
实现一键从搜索到批量生成小红书图文。

优化要点：
- 搜索逻辑统一在此层，TopicSplitter 只负责拆分
- 并发 DB 写入改为串行（共用同一个 Session，避免竞态）
- 支持 SSE 流式进度回报（每完成一个角度推送一次事件）
- 全局超时保护（默认 180 秒）

使用方式：
    from app.ai.services.xhs.batch_generator import batch_generator_service

    # 同步模式（等待全部完成）
    result = await batch_generator_service.generate_batch(
        topic="2024年最好用的防晒霜",
        count=7, style="casual",
        user_id=1, db=db_session,
    )

    # 流式模式（每完成一个推送一次）
    async for event in batch_generator_service.generate_batch_stream(...):
        print(event)  # {"event": "progress", "data": {...}}
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.services.xhs.topic_splitter import topic_splitter_service
from app.ai.services.xhs.content import XHSContentService
from app.ai.services.xhs.schemas import (
    BatchTaskResult,
    SearchSource,
    BatchFromSearchResponse,
)
from app.core.logger import logger

# 并发控制：最多同时 3 个 LLM 调用
MAX_CONCURRENT = 3
# 全局超时：整个批量生成不超过此时间（秒）
BATCH_TIMEOUT = 180


class BatchGeneratorService:
    """批量搜索生成编排服务

    步骤:
    1. 搜索 → 获取搜索结果
    2. 选题拆分 → 获取 N 个写作角度
    3. 并行生成文案 → 每个角度生成一篇小红书文案
    4. 串行创建任务 → 每篇文案依次创建一个 draft 任务（避免 DB Session 竞态）
    """

    def __init__(self):
        self._content_service = XHSContentService()

    # ==================== 搜索（统一入口） ====================

    async def _do_search(
        self,
        topic: str,
        provider: Optional[str],
        max_results: int,
    ) -> list[dict]:
        """执行搜索获取原始结果（供选题拆分和搜索来源使用）"""
        try:
            from app.ai.services.search import SearchService
            from app.ai.providers import get_provider
            from app.ai.schemas.search import SearchRequest

            ai_provider = get_provider("openai")
            search_service = SearchService(provider=ai_provider)

            search_response = await search_service.search(
                SearchRequest(
                    query=topic,
                    max_results=max_results,
                    include_summary=False,
                    provider=provider,
                ),
            )

            return [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet or "",
                    "content": r.content or "",
                }
                for r in search_response.results
            ]
        except Exception as e:
            logger.error("批量生成: 搜索失败 - {}", e)
            raise ValueError(f"搜索失败: {e}") from e

    # ==================== 同步模式（返回完整结果） ====================

    async def generate_batch(
        self,
        topic: str,
        count: int = 7,
        style: str = "casual",
        search_provider: Optional[str] = None,
        max_search_results: int = 8,
        copy_length: str = "medium",
        include_emoji: bool = True,
        model: Optional[str] = None,
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> BatchFromSearchResponse:
        """执行批量搜索生成全流程（同步等待全部完成）"""
        start_time = time.time()

        logger.info(
            "批量搜索生成开始: topic='{}', count={}, style={}, provider={}",
            topic, count, style, search_provider,
        )

        # ===== Step 1: 搜索 =====
        search_results = await self._do_search(
            topic, search_provider, max_search_results
        )

        if not search_results:
            raise ValueError("搜索未返回任何结果，请换一个主题或检查搜索服务配置")

        # 构建搜索来源列表
        search_sources = [
            SearchSource(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
            )
            for r in search_results
        ]

        # ===== Step 2: 选题拆分 =====
        angles = await topic_splitter_service.split_topics(
            topic=topic,
            search_results=search_results,
            count=count,
            model=model,
            user_id=user_id,
        )

        # ===== Step 3: 并行生成文案（受限并发），全局超时保护 =====
        elapsed_search = time.time() - start_time
        remaining_timeout = max(BATCH_TIMEOUT - elapsed_search, 30)

        try:
            content_results = await asyncio.wait_for(
                self._generate_all_contents(
                    angles=angles,
                    topic=topic,
                    style=style,
                    copy_length=copy_length,
                    include_emoji=include_emoji,
                    model=model,
                ),
                timeout=remaining_timeout,
            )
        except asyncio.TimeoutError:
            logger.error("批量生成: 全局超时 ({}s)，已完成的结果将返回", BATCH_TIMEOUT)
            content_results = [
                (angle, None, "全局超时，生成中断")
                for angle in angles
            ]

        # ===== Step 4: 串行创建任务（避免并发写 DB Session 竞态） =====
        batch_results: list[BatchTaskResult] = []
        success_count = 0
        failed_count = 0

        for angle, content_result, error in content_results:
            angle_title = angle.get("angle_title", "未知角度")

            if error:
                batch_results.append(BatchTaskResult(
                    angle_title=angle_title,
                    status="failed",
                    error=error,
                ))
                failed_count += 1
                continue

            # 串行写 DB
            task_id = None
            if user_id and db and content_result:
                task_id = await self._create_task(
                    db=db,
                    user_id=user_id,
                    topic=topic,
                    angle_title=angle_title,
                    content_result=content_result,
                    style=style,
                )

            batch_results.append(BatchTaskResult(
                task_id=task_id,
                angle_title=angle_title,
                title=content_result.titles[0] if content_result and content_result.titles else None,
                content=content_result.copywriting if content_result else None,
                tags=content_result.tags if content_result else None,
                status="success",
            ))
            success_count += 1

        elapsed = time.time() - start_time
        logger.info(
            "批量搜索生成完成: topic='{}', 成功={}, 失败={}, 耗时={:.1f}s",
            topic, success_count, failed_count, elapsed,
        )

        return BatchFromSearchResponse(
            topic=topic,
            tasks=batch_results,
            search_sources=search_sources,
            total=len(batch_results),
            success=success_count,
            failed=failed_count,
        )

    # ==================== 流式模式（逐个推送） ====================

    async def generate_batch_stream(
        self,
        topic: str,
        count: int = 7,
        style: str = "casual",
        search_provider: Optional[str] = None,
        max_search_results: int = 8,
        copy_length: str = "medium",
        include_emoji: bool = True,
        model: Optional[str] = None,
        user_id: Optional[int] = None,
        db: Optional[AsyncSession] = None,
    ) -> AsyncGenerator[dict, None]:
        """流式批量生成（SSE 用）：每完成一个角度推送一次事件

        Yields:
            dict 事件，格式:
            - {"event": "search_done", "data": {"sources_count": N, "sources": [...]}}
            - {"event": "split_done", "data": {"angles_count": N, "angles": [...]}}
            - {"event": "progress", "data": {"index": i, "total": N, "result": BatchTaskResult}}
            - {"event": "done", "data": BatchFromSearchResponse}
            - {"event": "error", "data": {"message": "..."}}
        """
        start_time = time.time()

        try:
            # Step 1: 搜索
            search_results, search_sources, search_event = await self._stream_search(
                topic, search_provider, max_search_results
            )
            if search_event:
                yield search_event
            if not search_results:
                return

            # Step 2: 选题拆分
            angles, split_event = await self._stream_split(
                topic, search_results, count, model
            )
            yield split_event

            # Step 3: 并行生成文案
            content_results = await self._generate_all_contents(
                angles=angles,
                topic=topic,
                style=style,
                copy_length=copy_length,
                include_emoji=include_emoji,
                model=model,
            )

            # Step 4: 串行创建任务并推送进度
            batch_results: list[BatchTaskResult] = []
            success_count = 0
            failed_count = 0
            async for progress_event in self._stream_create_tasks(
                content_results=content_results,
                angles_count=len(angles),
                topic=topic,
                style=style,
                user_id=user_id,
                db=db,
                batch_results_out=batch_results,
            ):
                if progress_event["data"]["result"]["status"] == "success":
                    success_count += 1
                else:
                    failed_count += 1
                yield progress_event

            # Step 5: 完成
            yield self._build_done_event(
                topic=topic,
                batch_results=batch_results,
                search_sources=search_sources,
                success_count=success_count,
                failed_count=failed_count,
                elapsed=time.time() - start_time,
            )

        except Exception as e:
            logger.exception("批量搜索生成流异常: {}", e)
            yield {"event": "error", "data": {"message": str(e)}}

    # ==================== 流式生成分步辅助 ====================

    async def _stream_search(
        self,
        topic: str,
        search_provider: Optional[str],
        max_search_results: int,
    ) -> tuple[list, list[SearchSource], Optional[dict]]:
        """Step 1: 搜索；返回 (search_results, search_sources, sse_event)

        搜索无结果时 sse_event 为 error 事件且 search_results 为空列表；
        否则为 search_done 事件。调用方据此判断是否终止。
        """
        search_results = await self._do_search(
            topic, search_provider, max_search_results
        )

        if not search_results:
            return [], [], {"event": "error", "data": {"message": "搜索未返回任何结果"}}

        search_sources = [
            SearchSource(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("snippet", ""),
            )
            for r in search_results
        ]

        event = {
            "event": "search_done",
            "data": {
                "sources_count": len(search_results),
                "sources": [s.model_dump() for s in search_sources],
            },
        }
        return search_results, search_sources, event

    async def _stream_split(
        self,
        topic: str,
        search_results: list,
        count: int,
        model: Optional[str],
    ) -> tuple[list, dict]:
        """Step 2: 选题拆分；返回 (angles, sse_split_done_event)"""
        angles = await topic_splitter_service.split_topics(
            topic=topic,
            search_results=search_results,
            count=count,
            model=model,
        )
        event = {
            "event": "split_done",
            "data": {
                "angles_count": len(angles),
                "angles": [
                    {
                        "angle_title": a.get("angle_title", ""),
                        "content_direction": a.get("content_direction", ""),
                    }
                    for a in angles
                ],
            },
        }
        return angles, event

    async def _stream_create_tasks(
        self,
        *,
        content_results: list,
        angles_count: int,
        topic: str,
        style: str,
        user_id: Optional[int],
        db: Optional[AsyncSession],
        batch_results_out: list[BatchTaskResult],
    ) -> AsyncGenerator[dict, None]:
        """Step 4: 串行创建任务并 yield 每个角度的 progress 事件

        `batch_results_out` 由调用方传入，本方法就地追加（供主流程汇总 done 事件用）。
        """
        for i, (angle, content_result, error) in enumerate(content_results):
            angle_title = angle.get("angle_title", f"角度{i + 1}")

            if error:
                result = BatchTaskResult(
                    angle_title=angle_title,
                    status="failed",
                    error=error,
                )
            else:
                task_id = None
                if user_id and db and content_result:
                    task_id = await self._create_task(
                        db=db,
                        user_id=user_id,
                        topic=topic,
                        angle_title=angle_title,
                        content_result=content_result,
                        style=style,
                    )

                result = BatchTaskResult(
                    task_id=task_id,
                    angle_title=angle_title,
                    title=content_result.titles[0] if content_result and content_result.titles else None,
                    content=content_result.copywriting if content_result else None,
                    tags=content_result.tags if content_result else None,
                    status="success",
                )

            batch_results_out.append(result)

            yield {
                "event": "progress",
                "data": {
                    "index": i,
                    "total": angles_count,
                    "result": result.model_dump(),
                },
            }

    def _build_done_event(
        self,
        *,
        topic: str,
        batch_results: list[BatchTaskResult],
        search_sources: list[SearchSource],
        success_count: int,
        failed_count: int,
        elapsed: float,
    ) -> dict:
        """Step 5: 构造 SSE "done" 事件数据"""
        final_response = BatchFromSearchResponse(
            topic=topic,
            tasks=batch_results,
            search_sources=search_sources,
            total=len(batch_results),
            success=success_count,
            failed=failed_count,
        )
        return {
            "event": "done",
            "data": {
                **final_response.model_dump(),
                "elapsed_seconds": round(elapsed, 1),
            },
        }

    # ==================== 并行文案生成 ====================

    async def _generate_all_contents(
        self,
        *,
        angles: list[dict],
        topic: str,
        style: str,
        copy_length: str,
        include_emoji: bool,
        model: Optional[str],
    ) -> list[tuple[dict, object, Optional[str]]]:
        """并行生成所有角度的文案

        Returns:
            [(angle_dict, content_result_or_None, error_str_or_None), ...]
        """
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _gen(angle: dict, index: int):
            angle_title = angle.get("angle_title", f"角度{index + 1}")
            key_points = angle.get("key_points", [])
            content_direction = angle.get("content_direction", "")

            async with semaphore:
                try:
                    logger.info("批量生成: 开始第 {} 个角度 - {}", index + 1, angle_title)
                    outline = self._build_outline_from_angle(
                        angle_title, key_points, content_direction
                    )

                    content_result = await self._content_service.generate_content(
                        topic=angle_title,
                        outline=outline,
                        style=style,
                        model=model,
                        copy_length=copy_length,
                        include_emoji=include_emoji,
                    )
                    return (angle, content_result, None)

                except Exception as e:
                    logger.warning("批量生成: 角度 '{}' 失败 - {}", angle_title, e)
                    return (angle, None, str(e))

        tasks = [_gen(angle, i) for i, angle in enumerate(angles)]
        return list(await asyncio.gather(*tasks))

    # ==================== 辅助方法 ====================

    @staticmethod
    def _build_outline_from_angle(
        angle_title: str,
        key_points: list[str],
        content_direction: str,
    ) -> str:
        """从角度信息构建 outline 文本"""
        lines = [f"选题：{angle_title}"]
        if content_direction:
            lines.append(f"方向：{content_direction}")
        if key_points:
            lines.append("核心要点：")
            for i, point in enumerate(key_points, 1):
                lines.append(f"  {i}. {point}")
        return "\n".join(lines)

    @staticmethod
    async def _create_task(
        *,
        db: AsyncSession,
        user_id: int,
        topic: str,
        angle_title: str,
        content_result,
        style: str,
    ) -> Optional[int]:
        """创建 XHS 任务（draft 状态）

        注意：此方法必须串行调用（不能并发），因为共用同一个 db Session。
        """
        try:
            from app.schemas.xhs_task import XHSTaskCreate, PageContent
            from app.crud.xhs_task import xhs_task

            # 构建单页任务（文案作为内容）
            pages = [
                PageContent(
                    page_num=1,
                    content=content_result.copywriting or "",
                    title=content_result.titles[0] if content_result.titles else angle_title,
                ),
            ]

            task_data = XHSTaskCreate(
                title=content_result.titles[0] if content_result.titles else angle_title,
                topic=topic,
                status="draft",
                style=style,
                pages=pages,
            )

            task = await xhs_task.create_for_user(
                db, obj_in=task_data, user_id=user_id
            )

            # 保存文案数据
            copywriting_data = {
                "titles": content_result.titles,
                "copywriting": content_result.copywriting,
                "tags": content_result.tags,
                "emoji_title": content_result.emoji_title,
            }
            await xhs_task.update_copywriting(db, task=task, copywriting=copywriting_data)
            await db.commit()

            logger.info("批量生成: 任务已创建 task_id={}, angle='{}'", task.id, angle_title)
            return task.id

        except Exception as e:
            logger.warning("批量生成: 创建任务失败 - {}", e)
            try:
                await db.rollback()
            except Exception as rollback_err:
                logger.warning("批量生成: 任务创建失败后 rollback 异常（已忽略）: {}", rollback_err)
            return None


# 模块级单例
batch_generator_service = BatchGeneratorService()
