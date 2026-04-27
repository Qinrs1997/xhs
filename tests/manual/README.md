# 手动调试脚本 (tests/manual/)

> 本目录下是**非 pytest**的手动调试脚本，用于本地联调或快速验证外部服务。
> 这些脚本**不会被 `pytest` 自动收集**（已在 `pyproject.toml` 的 `testpaths` 中排除）。

## 运行方式

```bash
# 激活 python 环境后直接 python 运行
cd backend
python tests/manual/test_db_connection.py
python tests/manual/test_server.py       # 先启动 uvicorn
python tests/manual/test_siliconflow_direct.py  # 需设置 SILICONFLOW_API_KEY 环境变量
```

## 文件用途

| 脚本 | 用途 | 依赖 |
|------|------|------|
| `debug_db.py` | MySQL 连接调试（尝试多种方式） | 需修改里面的 `password` |
| `test_db_connection.py` | 数据库连通性检测 | .env 配置 |
| `test_server.py` | 启动后接口冒烟测试（健康/登录） | uvicorn 已启动 |
| `test_ai_api.py` | AI API 调试 | AI_API_KEY |
| `test_project_ai.py` | AI 项目集成联调 | .env + 服务启动 |
| `test_siliconflow.py` | 通过项目代码调用 SiliconFlow | .env |
| `test_siliconflow_direct.py` | 直接 HTTP 调用 SiliconFlow（不走项目） | `SILICONFLOW_API_KEY` env |
| `test_image_xhs.py` | XHS 图片生成联调 | .env + 服务启动 |
| `test_xhs_e2e.py` | XHS 端到端人工回归 | .env + 真实 API Key |

## 维护说明

- ⚠️ 这些脚本**不受 CI 保护**，可能随时因外部依赖（真实 API、数据库）变化而失效
- 🧹 发现废弃脚本时直接删除或并入真正的 pytest 测试
- ✅ 真正的 pytest 测试请放在:
  - `tests/unit/` — 单元测试（只依赖内存 mock）
  - `tests/integration/` — 集成测试（使用 TestClient + in-memory SQLite）
