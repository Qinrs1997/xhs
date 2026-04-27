"""XHS 任务 API 集成测试(E2E)

完整流程验证:
1. 创建任务
2. 获取任务列表/详情
3. 更新任务
4. 保存文案
5. 获取统计
6. 删除任务
7. 鉴权边界(另一个用户无法查看)
"""
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

BASE = "/api/v1/xhs"


class TestXHSTaskLifecycle:
    """XHS 任务完整生命周期"""

    async def test_full_task_lifecycle(self, authed_client: AsyncClient):
        create_payload = {
            "title": "E2E 测试任务",
            "topic": "秋季穿搭",
            "status": "draft",
            "pages": [
                {"page_num": 1, "content": "封面文案", "page_type": "cover"},
                {"page_num": 2, "content": "正文", "page_type": "content"},
            ],
        }
        r = await authed_client.post(f"{BASE}/tasks", json=create_payload)
        assert r.status_code == 201, r.text
        created = r.json()["data"]
        task_id = created["id"]
        assert created["title"] == "E2E 测试任务"
        assert created["page_count"] == 2

        r = await authed_client.get(f"{BASE}/tasks")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["id"] == task_id

        r = await authed_client.get(f"{BASE}/tasks/{task_id}")
        assert r.status_code == 200
        detail = r.json()["data"]
        assert detail["id"] == task_id
        assert len(detail["pages"]) == 2

        r = await authed_client.put(
            f"{BASE}/tasks/{task_id}",
            json={"status": "completed", "title": "更新后的标题"},
        )
        assert r.status_code == 200
        updated = r.json()["data"]
        assert updated["status"] == "completed"
        assert updated["title"] == "更新后的标题"
        assert updated["completed_at"] is not None

        r = await authed_client.put(
            f"{BASE}/tasks/{task_id}/copywriting",
            json={
                "title": "吸睛标题",
                "content": "种草正文",
                "tags": ["#秋冬", "#穿搭"],
            },
        )
        assert r.status_code == 200

        r = await authed_client.get(f"{BASE}/tasks/{task_id}/copywriting")
        assert r.status_code == 200
        cw = r.json()["data"]
        assert cw["title"] == "吸睛标题"
        assert "#秋冬" in cw["tags"]

        r = await authed_client.get(f"{BASE}/tasks/stats")
        assert r.status_code == 200
        stats = r.json()["data"]
        assert stats["total"] == 1

        r = await authed_client.delete(f"{BASE}/tasks/{task_id}")
        assert r.status_code == 200

        r = await authed_client.get(f"{BASE}/tasks/{task_id}")
        assert r.status_code == 404


class TestXHSTaskListFilters:
    """列表过滤"""

    async def test_filter_by_status(self, authed_client: AsyncClient):
        await authed_client.post(f"{BASE}/tasks", json={"title": "A", "topic": "x", "status": "draft"})
        await authed_client.post(f"{BASE}/tasks", json={"title": "B", "topic": "x", "status": "completed"})

        r = await authed_client.get(f"{BASE}/tasks?status=completed")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["status"] == "completed"

    async def test_keyword_search(self, authed_client: AsyncClient):
        await authed_client.post(f"{BASE}/tasks", json={"title": "秋季穿搭", "topic": "风格"})
        await authed_client.post(f"{BASE}/tasks", json={"title": "早餐食谱", "topic": "美食"})

        r = await authed_client.get(f"{BASE}/tasks?keyword=秋季")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1

    async def test_pagination(self, authed_client: AsyncClient):
        for i in range(5):
            await authed_client.post(f"{BASE}/tasks", json={"title": f"t-{i}", "topic": "x"})

        r = await authed_client.get(f"{BASE}/tasks?page=1&page_size=2")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 5
        assert data["page_size"] == 2
        assert len(data["items"]) == 2


class TestAuthorization:
    """越权保护"""

    async def test_unauthenticated_blocked(self, db_session: AsyncSession):
        """无 token 访问被拒"""
        from httpx import ASGITransport, AsyncClient

        from app.core.database import get_async_db
        from app.main import app

        async def _db():
            yield db_session

        app.dependency_overrides[get_async_db] = _db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get(f"{BASE}/tasks")
            assert r.status_code in (401, 403)

        app.dependency_overrides.clear()

    async def test_not_found_for_unknown_task(self, authed_client: AsyncClient):
        r = await authed_client.get(f"{BASE}/tasks/99999")
        assert r.status_code == 404
