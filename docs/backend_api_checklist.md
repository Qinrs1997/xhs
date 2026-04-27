# 后端接口检查清单 —— XHS 创作流程

> 前端完整创作流程涉及以下后端接口，请逐一排查是否正常工作。
> 基础路径：`/api/v1`

---

## 🔴 核心问题：保存后历史记录为空

### 完整数据链路

```
用户输入主题 → AI搜索 → 生成大纲 → 保存任务 → 历史记录列表 → 恢复任务
```

前端调用顺序：

```
1. POST /api/v1/ai/search              → 搜索（返回 search_id）
2. POST /api/v1/xhs/outline            → 生成大纲（返回 task_id + pages）
3. POST /api/v1/xhs/tasks/save         → ★ 保存任务（大纲完成时自动触发）
4. POST /api/v1/xhs/prompts            → 生成提示词
5. POST /api/v1/xhs/tasks/save         → ★ 保存任务（提示词完成时自动触发）
6. GET  /api/v1/xhs/tasks              → 历史记录列表
7. GET  /api/v1/xhs/tasks/{id}         → 任务详情（恢复用）
```

---

## ⭐ 请重点排查的接口

### 1. `POST /api/v1/xhs/tasks/save` — 保存/创建任务

**这是最关键的接口，用于保存大纲、提示词等数据。**

#### 前端发送的 payload 结构：

```json
{
  "task_id": 123,           // 首次保存时为后端 outline 返回的 task_id
  "title": "秋季穿搭分享",   // 等于 topic
  "topic": "秋季穿搭分享",
  "pages": [
    {
      "page_num": 1,
      "content": "封面文案...",
      "image_url": null,
      "thumbnail_url": null,
      "original_url": null,
      "image_prompt": "a fashion outfit...",
      "title": "秋日穿搭灵感",
      "page_type": "cover",
      "extra": {
        "status": "pending",
        "error": null,
        "type": "cover",
        "title": "秋日穿搭灵感"
      }
    }
    // ... 更多页面
  ],
  "status": "draft",
  "template_id": null,
  "search_id": 5,           // 关联的搜索历史 ID（可能为 undefined）
  "autosave": false
}
```

#### 期望返回：

```json
{
  "task_id": 123,          // ★ 必须返回！前端用这个同步 URL
  "success": true,
  "saved_at": "2026-03-25T10:00:00Z"
}
```

> [!IMPORTANT]
> **关键确认点：**
> 1. 后端收到 `task_id` 非 null 时，是**更新**还是**新建**？
> 2. 响应中 `task_id` 字段是否存在？（前端依赖这个字段做 URL 同步）
> 3. 如果 `task_id` 不存在于数据库中（比如是 outline 接口临时生成的），后端是否会自动创建？
> 4. 认证失败（401）时是否有明确错误提示？

---

### 2. `POST /api/v1/xhs/outline` — 生成大纲

#### 前端发送：

```json
{
  "topic": "秋季穿搭分享\n\n【参考资料】:\n- 标题1: 摘要1\n...\n\n【AI 总结】: ...",
  "images": [],
  "template_id": null,
  "model": "gpt-4",
  "page_count": 6,
  "tone": "casual",
  "language": "zh"
}
```

#### 期望返回：

```json
{
  "task_id": "123",        // ★ 这个 ID 必须有效，后续保存用它
  "outline": "大纲文本...",
  "pages": [
    {
      "index": 0,
      "content": "封面文案...",
      "page_type": "cover",
      "title": "标题",
      "image_prompt": null
    }
    // ...
  ]
}
```

> [!IMPORTANT]
> **关键确认点：**
> 1. 返回的 `task_id` 是否在数据库中已创建？还是仅仅是一个临时 ID？
> 2. 如果是临时 ID，后续 `POST /tasks/save` 能否用这个 ID 保存？
> 3. `task_id` 的格式是数字还是字符串？（前端会用 `String()` 转换）

---

### 3. `GET /api/v1/xhs/tasks` — 任务列表（历史记录）

#### 前端发送：

```
GET /api/v1/xhs/tasks
GET /api/v1/xhs/tasks?page=1&page_size=20&status=xxx
```

#### 期望返回：

```json
{
  "items": [
    {
      "id": 123,
      "title": "秋季穿搭分享",
      "topic": "秋季穿搭分享",
      "status": "draft",
      "page_count": 6,
      "template_id": null,
      "search_id": 5,
      "has_copywriting": false,
      "created_at": "2026-03-25T10:00:00Z",
      "updated_at": "2026-03-25T10:00:00Z",
      "pages": [
        {
          "page_num": 1,
          "content": "...",
          "image_url": null,
          "thumbnail_url": null,
          "title": "标题",
          "page_type": "cover",
          "extra": { "status": "pending" }
        }
      ]
    }
  ],
  "total": 1
}
```

> [!WARNING]
> **关键确认点：**
> 1. 如果 status="draft" 的任务被过滤掉了，历史记录会显示为空！
> 2. 请确认：**默认是否返回所有状态的任务**（包括 draft）？
> 3. `pages` 字段是否包含在列表接口中？（有些接口为了性能不返回 pages detail）

---

### 4. `GET /api/v1/xhs/tasks/{id}` — 任务详情

#### 期望返回：

```json
{
  "id": 123,
  "title": "秋季穿搭分享",
  "topic": "秋季穿搭分享",
  "status": "draft",
  "search_id": 5,
  "has_copywriting": false,
  "created_at": "2026-03-25T10:00:00Z",
  "updated_at": "2026-03-25T10:00:00Z",
  "pages": [
    {
      "page_num": 1,
      "content": "文案...",
      "image_url": null,
      "thumbnail_url": null,
      "original_url": null,
      "image_prompt": "prompt...",
      "title": "标题",
      "page_type": "cover",
      "extra": {
        "status": "pending",
        "type": "cover",
        "title": "标题"
      }
    }
  ]
}
```

> [!IMPORTANT]
> **关键确认点：**
> 1. `pages` 字段是否完整返回（包含 `image_prompt`、`extra.status` 等）？
> 2. ID 类型是否一致（前端用 `Number(id)` 请求）？

---

### 5. `POST /api/v1/ai/search` — AI 搜索

#### 期望返回：

```json
{
  "query": "秋季穿搭",
  "results": [
    { "title": "...", "url": "...", "snippet": "...", "score": 0.95 }
  ],
  "summary": "AI 总结...",
  "search_id": 5    // ★ 必须返回，前端用于关联任务
}
```

> [!IMPORTANT]
> **关键确认点：**
> 1. `search_id` 是否返回？（前端在 save 任务时会带上这个 ID）
> 2. 搜索结果是否自动保存到搜索历史表？

---

### 6. `GET /api/v1/ai/search/history/{id}` — 搜索历史详情

用于任务恢复时拉取搜索结果。

#### 期望返回：

```json
{
  "id": 5,
  "query": "秋季穿搭",
  "results": [
    { "title": "...", "url": "...", "snippet": "...", "score": 0.95 }
  ],
  "full_summary": "AI 完整总结...",
  "summary": "简短总结",
  "status": "completed"
}
```

---

## 📋 后端自查清单

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | `POST /xhs/outline` 返回的 `task_id` 是有效的数据库 ID | ⬜ |
| 2 | `POST /xhs/tasks/save` 能用 outline 返回的 `task_id` 保存 | ⬜ |
| 3 | `POST /xhs/tasks/save` 响应体包含 `task_id` 字段 | ⬜ |
| 4 | `POST /xhs/tasks/save` 的 `pages` 数组能正确持久化 | ⬜ |
| 5 | `GET /xhs/tasks` 列表**默认包含 draft 状态**的任务 | ⬜ |
| 6 | `GET /xhs/tasks` 列表返回正确的 `items` 和 `total` | ⬜ |
| 7 | `GET /xhs/tasks/{id}` 详情包含完整 `pages`（含 [extra](file:///e:/shiyong/xhs_vue/src/views/xhs/components/CreatorSearch.vue#410-417)） | ⬜ |
| 8 | `POST /ai/search` 响应包含 `search_id` 字段 | ⬜ |
| 9 | `GET /ai/search/history/{id}` 能通过 search_id 获取搜索结果 | ⬜ |
| 10 | 所有接口认证正常（token 有效时不返回 401） | ⬜ |

---

## 🔧 快速排查命令

后端同事可以用以下命令快速测试（替换 `YOUR_TOKEN` 和 `YOUR_TASK_ID`）：

```bash
# 1. 测试任务保存
curl -X POST http://127.0.0.1:8999/api/v1/xhs/tasks/save \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task_id": null, "title": "测试保存", "topic": "测试", "pages": [{"page_num": 1, "content": "test", "page_type": "cover", "title": "test", "extra": {"status": "pending"}}], "status": "draft"}'

# 2. 测试任务列表
curl http://127.0.0.1:8999/api/v1/xhs/tasks \
  -H "Authorization: Bearer YOUR_TOKEN"

# 3. 测试任务详情
curl http://127.0.0.1:8999/api/v1/xhs/tasks/YOUR_TASK_ID \
  -H "Authorization: Bearer YOUR_TOKEN"

# 4. 测试大纲生成（返回 task_id）
curl -X POST http://127.0.0.1:8999/api/v1/xhs/outline \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic": "测试主题", "page_count": 3}'
```

---

## ⚡ 最可能的问题

根据前端代码分析，**最可能导致历史记录为空的原因**：

1. **`POST /xhs/tasks/save` 静默失败** — 接口返回了错误但被前端 catch 吞掉了（已添加日志）
2. **`GET /xhs/tasks` 过滤了 draft 状态** — 如果列表接口默认只返回 `completed` 状态的任务，那 draft 的大纲就看不到
3. **outline 的 `task_id` 和 tasks/save 不兼容** — outline 返回的是临时 task_id，save 接口不认识这个 ID
4. **认证问题** — Token 过期或未携带，导致保存被 401 拒绝
