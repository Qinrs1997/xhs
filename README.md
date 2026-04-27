# XHS Backend

小红书 AI 图文创作平台后端服务。项目基于 FastAPI + SQLAlchemy 2.0 Async + MySQL 构建，负责用户认证、AI 搜索、文案生成、图片生成、任务历史、模板管理、会员积分、支付和管理员后台 API。

## 最新能力

- 小红书图文创作：主题输入、联网搜索增强、AI 大纲、文案审核、图片生成、任务保存。
- 图片生成双模式：逐页画质模式，以及 2x2 batch grid 省钱模式，后端会把合成图切割回独立页面。
- 模板风格透传：支持 `style_prompt`、`negative_style_prompt`、`image_grid_config` 和模板默认图片模式。
- 图片质量链路：生成图保存原图和缩略图，任务恢复和下载优先使用原图字段。
- 搜索与文案重试：搜索生成失败时最多自动重试，降低用户直接看到错误的概率。
- 历史记录顺序：任务列表按更新时间倒序，页面按 `page_num` 归一化，避免图文顺序错乱。
- 积分与会员：图片生成、重绘、订阅等操作接入积分扣除、流水记录和管理员统计。
- 管理能力：AI 配置、模板管理、积分管理、用户、角色、部门、公告、定时任务和审计日志。
- 生产日志：关键业务路径增加 request id、用户、任务、积分、生成模式、耗时和错误上下文。

## 技术栈

| 类型 | 技术 |
| --- | --- |
| Web 框架 | FastAPI 0.135、Uvicorn |
| 数据层 | SQLAlchemy 2.0 AsyncSession、Alembic、MySQL 8、asyncmy |
| 数据校验 | Pydantic 2、pydantic-settings |
| 认证授权 | JWT、角色权限、登录锁定、密码强度校验 |
| AI 调用 | LiteLLM、OpenAI 兼容接口、SiliconFlow、APIMart 图像生成 |
| 搜索 | Tavily、Brave、Serper、SearXNG、DuckDuckGo 适配层 |
| 图片处理 | Pillow、可选 numpy 加速网格切割 |
| 缓存/任务 | Redis 可选、内存缓存、调度器 |
| 日志监控 | Loguru、请求追踪、操作日志、Prometheus 指标 |
| 支付 | 支付宝 SDK、mock 支付模式 |

## 目录结构

```text
backend/
├── app/
│   ├── ai/                         # AI provider、prompt、XHS 生成服务
│   │   ├── prompts/templates/xhs/   # 大纲/文案/图片提示词模板
│   │   └── services/xhs/            # outline/content/image/batch 业务
│   ├── api/v1/endpoints/            # API 路由
│   │   ├── xhs_generate/            # 大纲、文案、图片、提示词接口
│   │   ├── xhs_tasks/               # 任务保存、历史、下载、统计
│   │   ├── credits_*.py             # 积分和会员接口
│   │   └── ai_admin/                # AI 管理配置
│   ├── core/                        # 配置、DB、安全、日志、中间件、图片处理
│   ├── crud/                        # 数据访问层
│   ├── models/                      # SQLAlchemy 模型
│   ├── schemas/                     # Pydantic Schema
│   └── services/                    # 会员、积分、支付、用户等服务
├── alembic/                         # 数据库迁移
├── config/                          # settings.toml / settings.prod.toml
├── docs/                            # 文档
├── scripts/                         # 运维和调试脚本
├── systemd/                         # systemd 示例
├── tests/                           # unit / integration / manual
├── requirements.txt
└── pyproject.toml
```

## 快速开始

### 1. 准备环境

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS：

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
copy .env.example .env
```

至少需要配置：

```env
MYSQL_PASSWORD=your_database_password
SECRET_KEY=your-secret-key-at-least-32-characters-long-random
AI_API_KEY=your-ai-api-key
IMAGE_API_KEY=your-apimart-api-key
TAVILY_API_KEY=your-search-api-key
BOOTSTRAP_ADMIN_PASSWORD=change_this_to_strong_password
```

真实密钥只放 `.env` 或服务器环境变量，不要写入 `config/settings.toml`。

### 3. 启动服务

默认端口在 `config/settings.toml` 中为 `8999`：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8999 --reload
```

访问：

```text
http://localhost:8999/docs
http://localhost:8999/health
```

生产环境可以通过配置或 systemd 覆盖端口，例如线上使用 `9001`。

## 关键配置

配置优先级：

```text
环境变量 > .env > settings.{env}.toml > settings.toml > 代码默认值
```

常用配置位置：

| 配置 | 位置 |
| --- | --- |
| 应用端口、环境 | `config/settings.toml [app]` |
| MySQL | `config/settings.toml [database]` + `MYSQL_*` |
| Redis | `config/settings.toml [redis]` + `REDIS_*` |
| AI 文本模型 | `config/settings.toml [ai.openai]` + `AI_API_KEY` |
| APIMart 图片模型 | `config/settings.toml [ai.image]` + `IMAGE_API_KEY` |
| XHS batch grid | `config/settings.toml [ai.xhs.batch_grid]` |
| CORS | `config/settings.toml [security.cors]` |
| 支付 | `config/settings.toml [payment]` |

## 主要 API

| 模块 | 路径 | 说明 |
| --- | --- | --- |
| 健康检查 | `/health` | 服务健康状态 |
| 认证 | `/api/v1/auth` | 登录、注册、验证码、密码重置 |
| AI 配置 | `/api/v1/ai/config` | 前端可用模型、默认模型 |
| AI 搜索 | `/api/v1/ai/search` | 联网搜索和历史 |
| XHS 创作 | `/api/v1/xhs/outline` | 生成图文大纲 |
| XHS 文案 | `/api/v1/xhs/content` | 生成/优化小红书文案 |
| XHS 图片 | `/api/v1/xhs/image/stream` | SSE 流式图片生成 |
| XHS 重绘 | `/api/v1/xhs/image/regenerate` | 单页重绘 |
| XHS 批量重绘 | `/api/v1/xhs/image/batch_grid/regenerate` | 2x2 网格省钱重绘 |
| XHS 任务 | `/api/v1/xhs/tasks` | 保存、列表、详情、下载、统计 |
| XHS 模板 | `/api/v1/xhs/templates` | 用户模板市场 |
| 模板管理 | `/api/v1/admin/xhs/templates` | 管理员模板管理 |
| 积分 | `/api/v1/credits` | 余额、流水、签到 |
| 会员 | `/api/v1/membership` | 方案、订阅、会员状态 |
| 积分管理 | `/api/v1/admin/credits` | 管理员充值、扣除、统计 |
| 支付 | `/api/v1/payment` | 订单、支付通知、退款 |

## 图片生成链路

### 画质模式 `per_page`

每页单独调用图片模型，可设置 `images_per_page=1..4` 生成候选图，前端选择最佳图回填页面。

### 省钱模式 `batch_grid`

后端将 2-4 页提示词组合成 2x2 网格提示词，一次调用图片模型生成合成图，再通过 `ImageProcessor.split_grid` 切割成独立页面并保存原图/缩略图。

依赖：

- `Pillow` 是必需依赖。
- `numpy` 可用于更稳的图像分析切割；如果环境缺失，应安装到后端 venv，避免运行时 `ModuleNotFoundError`。

## 积分和日志

- 图片生成、重绘、批量重绘、会员订阅均应记录积分流水。
- 关键日志字段包括：`request_id`、`user_id`、`task_id`、`generation_mode`、`api_calls`、`credits`、`elapsed`、错误堆栈。
- 管理员可通过积分管理接口查看用户余额、流水和统计。

## 测试

常用单元测试：

```bash
pytest tests/unit/test_xhs_task.py tests/unit/test_xhs_batch_grid_prompt.py tests/unit/test_xhs_outline_utils.py tests/unit/test_xhs_generation_retry.py -q
```

完整自动收集测试：

```bash
pytest
```

代码质量：

```bash
ruff check .
ruff format .
```

## 部署

推荐 systemd + venv：

```bash
cd /home/lighthouse/projects/xhs-backend
venv/bin/pip install -r requirements.txt
venv/bin/alembic upgrade head
systemctl restart xhs-backend.service
systemctl status xhs-backend.service --no-pager -l
```

Nginx 反代示例：

```nginx
location ^~ /api/ {
    proxy_pass http://127.0.0.1:9001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_buffering off;
}

location ^~ /uploads/ {
    proxy_pass http://127.0.0.1:9001;
}
```

## 提交注意

不要提交以下内容：

- `.env`
- `logs/`
- `uploads/`
- `venv/`
- `.pytest_cache/`
- `backend.bundle`
- 任何真实 API Key、数据库密码、支付私钥

## 面试可讲点

- FastAPI 分层架构：API、Schema、CRUD、Service、AI Provider 解耦。
- SSE 流式图片生成：前端能实时接收页面状态和图片结果。
- Batch grid 省钱模式：一次图片 API 生成多页，再切割回独立页面。
- 模板风格约束：模板配置贯穿大纲、文案、图片提示词生成。
- 积分一致性：业务操作统一走积分服务，保留余额变更流水和日志上下文。
- 历史恢复可靠性：页面顺序归一化、原图字段兜底、任务按更新时间倒序。
