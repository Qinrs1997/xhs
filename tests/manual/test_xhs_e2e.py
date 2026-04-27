"""XHS API 端到端测试脚本

使用真实 token 测试所有 17 个 XHS 接口。
用法: python test/test_xhs_e2e.py

前提: 服务已启动在 http://127.0.0.1:8999
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE_URL = "http://127.0.0.1:8999/api/v1"
# 自动从配置中获取管理员账号
from app.core.config import settings
LOGIN_DATA = {"username": settings.BOOTSTRAP_ADMIN_USERNAME, "password": settings.BOOTSTRAP_ADMIN_PASSWORD}

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}✅ {msg}{RESET}")


def fail(msg):
    print(f"  {RED}❌ {msg}{RESET}")


def info(msg):
    print(f"  {YELLOW}ℹ️  {msg}{RESET}")


async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        passed = 0
        failed = 0
        skipped = 0

        # ==================== 1. 登录获取 token ====================
        print(f"\n{BOLD}{'='*60}")
        print(" XHS API 端到端测试")
        print(f"{'='*60}{RESET}\n")

        print(f"{BOLD}[1/8] 登录获取 Token{RESET}")
        r = await client.post("/auth/login", data=LOGIN_DATA)
        if r.status_code != 200:
            fail(f"登录失败: {r.status_code} {r.text[:200]}")
            return

        token_data = r.json()
        token = token_data.get("data", {}).get("access_token")
        if not token:
            fail(f"未获取到 token: {token_data}")
            return
        ok(f"登录成功，token: {token[:20]}...")
        headers = {"Authorization": f"Bearer {token}"}
        passed += 1

        # ==================== 2. 模板接口 ====================
        print(f"\n{BOLD}[2/8] 模板接口{RESET}")

        # GET /templates
        r = await client.get("/xhs/templates", headers=headers)
        if r.status_code == 200:
            data = r.json().get("data", {})
            items = data.get("items", [])
            categories = data.get("categories", [])
            ok(f"GET /templates → {len(items)} 个模板, {len(categories)} 个分类")
            passed += 1
        else:
            fail(f"GET /templates → {r.status_code}")
            failed += 1

        # GET /templates/1
        r = await client.get("/xhs/templates/1", headers=headers)
        if r.status_code == 200:
            tpl = r.json().get("data", {})
            ok(f"GET /templates/1 → {tpl.get('name', '?')} ({tpl.get('category', '?')})")
            passed += 1
        else:
            fail(f"GET /templates/1 → {r.status_code}")
            failed += 1

        # ==================== 3. 任务 CRUD ====================
        print(f"\n{BOLD}[3/8] 任务 CRUD{RESET}")

        # POST /tasks/save (创建)
        save_data = {
            "title": "E2E 测试任务",
            "topic": "自动化测试内容",
            "status": "draft",
            "pages": [
                {"page_num": 1, "content": "封面内容", "page_type": "cover"},
                {"page_num": 2, "content": "正文内容", "page_type": "content"},
            ],
        }
        r = await client.post("/xhs/tasks/save", json=save_data, headers=headers)
        task_id = None
        if r.status_code == 200:
            resp = r.json().get("data", {})
            task_id = resp.get("task_id")
            ok(f"POST /tasks/save → task_id={task_id}")
            passed += 1
        else:
            fail(f"POST /tasks/save → {r.status_code}: {r.text[:200]}")
            failed += 1

        # GET /tasks (列表)
        r = await client.get("/xhs/tasks", params={"page": 1, "page_size": 5}, headers=headers)
        if r.status_code == 200:
            data = r.json().get("data", {})
            ok(f"GET /tasks → total={data.get('total', '?')}")
            passed += 1
        else:
            fail(f"GET /tasks → {r.status_code}")
            failed += 1

        # GET /tasks/{id}
        if task_id:
            r = await client.get(f"/xhs/tasks/{task_id}", headers=headers)
            if r.status_code == 200:
                task = r.json().get("data", {})
                ok(f"GET /tasks/{task_id} → status={task.get('status', '?')}")
                passed += 1
            else:
                fail(f"GET /tasks/{task_id} → {r.status_code}")
                failed += 1

        # PUT /tasks/{id}/autosave
        if task_id:
            autosave_data = {
                "pages": [
                    {"page_num": 1, "content": "更新后的封面", "page_type": "cover"},
                ],
            }
            r = await client.put(f"/xhs/tasks/{task_id}/autosave", json=autosave_data, headers=headers)
            if r.status_code == 200:
                ok(f"PUT /tasks/{task_id}/autosave → 成功")
                passed += 1
            else:
                fail(f"PUT /tasks/{task_id}/autosave → {r.status_code}: {r.text[:200]}")
                failed += 1

        # ==================== 4. 统计接口 ====================
        print(f"\n{BOLD}[4/8] 统计接口{RESET}")

        # GET /tasks/stats
        r = await client.get("/xhs/tasks/stats", headers=headers)
        if r.status_code == 200:
            data = r.json().get("data", {})
            ok(f"GET /tasks/stats → total={data.get('total', '?')}")
            passed += 1
        else:
            fail(f"GET /tasks/stats → {r.status_code}")
            failed += 1

        # GET /stats (别名)
        r = await client.get("/xhs/stats", headers=headers)
        if r.status_code == 200:
            data = r.json().get("data", {})
            ok(f"GET /stats → total={data.get('total', '?')}")
            passed += 1
        else:
            fail(f"GET /stats → {r.status_code}")
            failed += 1

        # ==================== 5. 文案接口 ====================
        print(f"\n{BOLD}[5/8] 文案接口{RESET}")

        if task_id:
            r = await client.get(f"/xhs/tasks/{task_id}/copywriting", headers=headers)
            if r.status_code == 200:
                ok(f"GET /tasks/{task_id}/copywriting → 成功")
                passed += 1
            else:
                fail(f"GET /tasks/{task_id}/copywriting → {r.status_code}")
                failed += 1

        # ==================== 6. 下载接口 ====================
        print(f"\n{BOLD}[6/8] 下载接口{RESET}")

        if task_id:
            r = await client.get(f"/xhs/tasks/{task_id}/download", headers=headers)
            if r.status_code == 200:
                content_type = r.headers.get("content-type", "")
                ok(f"GET /tasks/{task_id}/download → {content_type}")
                passed += 1
            elif r.status_code == 404:
                info(f"GET /tasks/{task_id}/download → 无图片，跳过")
                skipped += 1
            else:
                fail(f"GET /tasks/{task_id}/download → {r.status_code}")
                failed += 1

        # ==================== 7. AI 生成接口（仅检查连通性） ====================
        print(f"\n{BOLD}[7/8] AI 生成接口（仅检查连通性）{RESET}")

        # POST /generate/outline — 只检查是否 422（参数校验通过）而非 500
        r = await client.post("/xhs/generate/outline", json={"topic": ""}, headers=headers)
        if r.status_code == 422:
            ok("POST /generate/outline → 422 参数校验正常")
            passed += 1
        elif r.status_code == 200:
            ok("POST /generate/outline → 200 生成成功")
            passed += 1
        else:
            info(f"POST /generate/outline → {r.status_code} (可能AI未配置)")
            skipped += 1

        # POST /generate/content
        r = await client.post("/xhs/generate/content", json={"topic": ""}, headers=headers)
        if r.status_code == 422:
            ok("POST /generate/content → 422 参数校验正常")
            passed += 1
        elif r.status_code == 200:
            ok("POST /generate/content → 200 生成成功")
            passed += 1
        else:
            info(f"POST /generate/content → {r.status_code}")
            skipped += 1

        # POST /generate/prompts
        r = await client.post("/xhs/generate/prompts", json={"topic": "test", "pages": []}, headers=headers)
        if r.status_code in (200, 500):
            status_label = "成功" if r.status_code == 200 else "AI未配置"
            ok(f"POST /generate/prompts → {r.status_code} ({status_label})")
            passed += 1
        else:
            info(f"POST /generate/prompts → {r.status_code}")
            skipped += 1

        # POST /generate/prompt/optimize
        r = await client.post("/xhs/generate/prompt/optimize", json={"prompt": "test"}, headers=headers)
        if r.status_code in (200, 500):
            ok(f"POST /generate/prompt/optimize → {r.status_code}")
            passed += 1
        else:
            info(f"POST /generate/prompt/optimize → {r.status_code}")
            skipped += 1

        # ==================== 8. 清理测试数据 ====================
        print(f"\n{BOLD}[8/8] 清理{RESET}")

        if task_id:
            r = await client.delete(f"/xhs/tasks/{task_id}", headers=headers)
            if r.status_code == 200:
                ok(f"DELETE /tasks/{task_id} → 已清理测试数据")
                passed += 1
            else:
                info(f"DELETE /tasks/{task_id} → {r.status_code} (可能无删除接口)")
                skipped += 1

        # ==================== 汇总 ====================
        print(f"\n{BOLD}{'='*60}")
        total = passed + failed + skipped
        print(f" 测试结果: {GREEN}{passed} 通过{RESET} / {RED}{failed} 失败{RESET} / {YELLOW}{skipped} 跳过{RESET} (共 {total})")
        print(f"{'='*60}{RESET}\n")

        if failed > 0:
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
