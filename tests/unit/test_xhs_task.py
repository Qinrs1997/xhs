"""XHS 任务 CRUD 单元测试

覆盖场景:
- 任务创建、更新、查询、删除
- 分页列表、筛选(status/keyword/date)
- 文案更新、page 字段批量更新
- Token 累加、完成时间标记
- 统计查询
"""
from datetime import timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.xhs_tasks._shared import _merge_image_fields
from app.api.v1.endpoints.xhs_tasks.save import (
    _derive_status_from_pages,
    _normalize_pages_for_save,
)
from app.core.timezone import now_utc
from app.crud.xhs_task import xhs_task
from app.models.user import User
from app.models.xhs_task import TaskStatus
from app.schemas.xhs_task import (
    PageContent,
    XHSTaskCreate,
    XHSTaskUpdate,
)
from app.schemas.xhs_task import (
    TaskStatus as SchemaTaskStatus,
)


@pytest_asyncio.fixture
async def task_user(db_session: AsyncSession) -> User:
    user = User(
        username="owner",
        email="owner@test.com",
        hashed_password="x",
        credits=100,
        vip_level="free",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        username="other",
        email="other@test.com",
        hashed_password="x",
        credits=100,
        vip_level="free",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _sample_pages():
    return [
        PageContent(page_num=1, content="封面文案", page_type="cover"),
        PageContent(page_num=2, content="正文一", page_type="content"),
        PageContent(page_num=3, content="正文二", page_type="content"),
    ]


class TestCreateForUser:
    """创建任务"""

    async def test_create_basic(self, db_session, task_user):
        obj = XHSTaskCreate(
            title="测试任务",
            topic="旅行攻略",
            status=SchemaTaskStatus.DRAFT,
        )
        task = await xhs_task.create_for_user(db_session, obj_in=obj, user_id=task_user.id)
        assert task.id is not None
        assert task.user_id == task_user.id
        assert task.title == "测试任务"
        assert task.status == TaskStatus.DRAFT
        assert task.page_count == 0

    async def test_create_with_pages(self, db_session, task_user):
        obj = XHSTaskCreate(
            title="带页面",
            topic="穿搭",
            pages=_sample_pages(),
        )
        task = await xhs_task.create_for_user(db_session, obj_in=obj, user_id=task_user.id)
        assert task.page_count == 3
        assert isinstance(task.pages, list)
        assert task.pages[0]["content"] == "封面文案"

    async def test_create_sorts_pages_by_page_num(self, db_session, task_user):
        obj = XHSTaskCreate(
            title="乱序页面",
            topic="穿搭",
            pages=[
                PageContent(page_num=3, content="第三页", page_type="content"),
                PageContent(page_num=1, content="封面", page_type="cover"),
                PageContent(page_num=2, content="第二页", page_type="content"),
            ],
        )

        task = await xhs_task.create_for_user(db_session, obj_in=obj, user_id=task_user.id)

        assert [page["content"] for page in task.pages] == ["封面", "第二页", "第三页"]
        assert [page["page_num"] for page in task.pages] == [1, 2, 3]


class TestUpdateTask:
    """更新任务"""

    async def test_update_status_marks_completion(self, db_session, task_user):
        created = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        updated = await xhs_task.update_task(
            db_session,
            task=created,
            obj_in=XHSTaskUpdate(status=SchemaTaskStatus.COMPLETED),
            user_id=task_user.id,
        )
        assert updated.status == TaskStatus.COMPLETED
        assert updated.completed_at is not None

    async def test_update_pages_recomputes_count(self, db_session, task_user):
        created = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        assert created.page_count == 3

        updated = await xhs_task.update_task(
            db_session,
            task=created,
            obj_in=XHSTaskUpdate(pages=_sample_pages()[:2]),
            user_id=task_user.id,
        )
        assert updated.page_count == 2


class TestGetByUser:
    """用户任务列表查询"""

    async def test_list_only_own_tasks(self, db_session, task_user, other_user):
        # task_user 两条,other_user 一条
        for i in range(2):
            await xhs_task.create_for_user(
                db_session,
                obj_in=XHSTaskCreate(title=f"mine-{i}", topic="t"),
                user_id=task_user.id,
            )
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="other-1", topic="t"),
            user_id=other_user.id,
        )

        items, total = await xhs_task.get_by_user(db_session, user_id=task_user.id)
        assert total == 2
        assert all(t.user_id == task_user.id for t in items)

    async def test_filter_by_status(self, db_session, task_user):
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="a", topic="t", status=SchemaTaskStatus.DRAFT),
            user_id=task_user.id,
        )
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="b", topic="t", status=SchemaTaskStatus.COMPLETED),
            user_id=task_user.id,
        )

        items, total = await xhs_task.get_by_user(
            db_session, user_id=task_user.id, status=TaskStatus.COMPLETED
        )
        assert total == 1
        assert items[0].status == TaskStatus.COMPLETED

    async def test_keyword_search_title_and_topic(self, db_session, task_user):
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="秋季穿搭", topic="风格"),
            user_id=task_user.id,
        )
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="其他", topic="秋季穿搭主题"),
            user_id=task_user.id,
        )
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="不相关", topic="美食"),
            user_id=task_user.id,
        )

        _items, total = await xhs_task.get_by_user(
            db_session, user_id=task_user.id, keyword="秋季穿搭"
        )
        assert total == 2

    async def test_limit_capped_at_100(self, db_session, task_user):
        items, _ = await xhs_task.get_by_user(
            db_session, user_id=task_user.id, limit=500
        )
        assert len(items) <= 100

    async def test_date_range_filter(self, db_session, task_user):
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        now = now_utc().replace(tzinfo=None)
        _items, total = await xhs_task.get_by_user(
            db_session,
            user_id=task_user.id,
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=1),
        )
        assert total == 1


class TestGetUserTask:
    """单任务查询"""

    async def test_get_own_task(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        found = await xhs_task.get_user_task(
            db_session, task_id=task.id, user_id=task_user.id
        )
        assert found is not None
        assert found.id == task.id

    async def test_get_others_task_returns_none(self, db_session, task_user, other_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        found = await xhs_task.get_user_task(
            db_session, task_id=task.id, user_id=other_user.id
        )
        assert found is None


class TestPageMutations:
    """页面字段更新"""

    async def test_update_page_field(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        updated = await xhs_task.update_page_field(
            db_session,
            task=task,
            page_index=0,
            updates={"image_url": "https://example.com/a.png"},
        )
        assert updated.pages[0]["image_url"] == "https://example.com/a.png"

    async def test_update_page_field_matches_page_num_when_storage_is_unsorted(
        self, db_session, task_user
    ):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        task.pages = [
            {"page_num": 2, "content": "正文一"},
            {"page_num": 1, "content": "封面文案"},
            {"page_num": 3, "content": "正文二"},
        ]

        updated = await xhs_task.update_page_field(
            db_session,
            task=task,
            page_index=0,
            updates={"image_url": "https://example.com/cover.png"},
        )

        assert updated.pages[0]["content"] == "封面文案"
        assert updated.pages[0]["image_url"] == "https://example.com/cover.png"
        assert updated.pages[1].get("image_url") is None

    async def test_update_page_field_out_of_range_is_safe(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        updated = await xhs_task.update_page_field(
            db_session, task=task, page_index=999, updates={"image_url": "x"}
        )
        assert len(updated.pages) == 3

    async def test_update_pages_batch(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        updated = await xhs_task.update_pages_batch(
            db_session,
            task=task,
            field_name="image_prompt",
            values=["p1", "p2", "p3"],
        )
        assert updated.pages[0]["image_prompt"] == "p1"
        assert updated.pages[2]["image_prompt"] == "p3"

    async def test_update_pages_batch_skips_none(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x", pages=_sample_pages()),
            user_id=task_user.id,
        )
        # 先给第 2 页写入旧值
        await xhs_task.update_pages_batch(
            db_session, task=task, field_name="image_prompt",
            values=["old1", "old2", "old3"],
        )
        # 第二次传 None 应跳过,保留旧值
        updated = await xhs_task.update_pages_batch(
            db_session,
            task=task,
            field_name="image_prompt",
            values=["p1", None, "p3"],
        )
        assert updated.pages[0]["image_prompt"] == "p1"
        assert updated.pages[1]["image_prompt"] == "old2"
        assert updated.pages[2]["image_prompt"] == "p3"


class TestTokensAndCopywriting:
    """文案/token 更新"""

    async def test_add_tokens_accumulates(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        await xhs_task.add_tokens(db_session, task=task, tokens=100)
        await xhs_task.add_tokens(db_session, task=task, tokens=50)
        assert task.total_tokens == 150

    async def test_update_copywriting(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        cw = {"title": "吸睛标题", "content": "正文...", "tags": ["#tag1"]}
        updated = await xhs_task.update_copywriting(
            db_session, task=task, copywriting=cw
        )
        assert updated.copywriting["title"] == "吸睛标题"


class TestDelete:
    """任务删除"""

    async def test_delete_own_task(self, db_session, task_user):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        deleted = await xhs_task.delete_user_task(
            db_session, task_id=task.id, user_id=task_user.id
        )
        assert deleted is not None
        assert (
            await xhs_task.get_user_task(
                db_session, task_id=task.id, user_id=task_user.id
            )
            is None
        )

    async def test_delete_others_task_returns_none(
        self, db_session, task_user, other_user
    ):
        task = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(title="t", topic="x"),
            user_id=task_user.id,
        )
        result = await xhs_task.delete_user_task(
            db_session, task_id=task.id, user_id=other_user.id
        )
        assert result is None


class TestStats:
    """任务统计"""

    async def test_stats_empty(self, db_session, task_user):
        stats = await xhs_task.get_user_task_stats(db_session, user_id=task_user.id)
        assert stats["total"] == 0
        assert stats["total_pages"] == 0
        assert stats["total_tokens"] == 0
        for s in TaskStatus:
            assert stats[s.value] == 0

    async def test_stats_with_tasks(self, db_session, task_user):
        await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(
                title="a", topic="x", pages=_sample_pages()[:2],
                status=SchemaTaskStatus.DRAFT,
            ),
            user_id=task_user.id,
        )
        t2 = await xhs_task.create_for_user(
            db_session,
            obj_in=XHSTaskCreate(
                title="b", topic="x", pages=_sample_pages(),
                status=SchemaTaskStatus.COMPLETED,
            ),
            user_id=task_user.id,
        )
        await xhs_task.add_tokens(db_session, task=t2, tokens=200)

        stats = await xhs_task.get_user_task_stats(db_session, user_id=task_user.id)
        assert stats["total"] == 2
        assert stats["total_pages"] == 5
        assert stats["total_tokens"] == 200
        assert stats[TaskStatus.DRAFT.value] == 1
        assert stats[TaskStatus.COMPLETED.value] == 1


class TestTaskSaveMergeHelpers:
    def test_merge_image_fields_preserves_stream_results(self):
        existing = [
            {
                "page_num": 1,
                "image_url": "/uploads/xhs/originals/a.png",
                "thumbnail_url": "/uploads/xhs/thumbnails/a.webp",
                "original_url": "/uploads/xhs/originals/a.png",
                "extra": {"status": "success"},
            }
        ]
        incoming = [{"page_num": 1, "extra": {"status": "pending"}}]

        _merge_image_fields(existing, incoming)

        assert incoming[0]["image_url"] == "/uploads/xhs/originals/a.png"
        assert incoming[0]["thumbnail_url"] == "/uploads/xhs/thumbnails/a.webp"
        assert incoming[0]["original_url"] == "/uploads/xhs/originals/a.png"
        assert incoming[0]["extra"]["status"] == "success"

    def test_merge_image_fields_matches_by_page_num_not_position(self):
        existing = [
            {"page_num": 2, "image_url": "/uploads/xhs/originals/page2.png"},
            {"page_num": 1, "image_url": "/uploads/xhs/originals/page1.png"},
        ]
        incoming = [{"page_num": 1}, {"page_num": 2}]

        _merge_image_fields(existing, incoming)

        assert incoming[0]["image_url"] == "/uploads/xhs/originals/page1.png"
        assert incoming[1]["image_url"] == "/uploads/xhs/originals/page2.png"

    def test_normalize_pages_for_save_sorts_by_page_num(self):
        pages = [
            {"page_num": 3, "content": "第三页"},
            {"page_num": 1, "content": "封面"},
            {"page_num": 2, "content": "第二页"},
        ]

        normalized = _normalize_pages_for_save(pages)

        assert [page["content"] for page in normalized] == ["封面", "第二页", "第三页"]
        assert [page["page_num"] for page in normalized] == [1, 2, 3]

    def test_derive_status_uses_merged_image_fields(self):
        pages = [
            {"page_num": 1, "image_url": "/uploads/xhs/originals/a.png"},
            {"page_num": 2, "thumbnail_url": "/uploads/xhs/thumbnails/b.webp"},
        ]

        assert _derive_status_from_pages(pages) == SchemaTaskStatus.COMPLETED
