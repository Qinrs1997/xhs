"""XHS 任务管理 API 聚合路由

原单文件 `xhs_tasks.py` (26KB / 746 行) 已按职责拆分到本包:

子模块           职责
--------------   -----------------------------------------
save.py          POST /tasks/save(创建+更新+autosave 三合一)
crud.py          GET /tasks, POST /tasks, GET/PUT/DELETE /tasks/{id}
copywriting.py   GET/PUT /tasks/{id}/copywriting
stats.py         GET /tasks/stats, GET /stats(别名)
autosave.py      PUT /tasks/{id}/autosave(独立轻量端点)
download.py      GET /tasks/{id}/download(ZIP 流式下载)

_shared.py       共享工具(_merge_image_fields / _extract_search_id /
                  _build_enhanced_stats / _cleanup_task_files / AutosaveRequest)

聚合后通过 `app.api.v1.router` 挂载到 `/xhs` 前缀,URL 与旧版完全兼容。
"""
from fastapi import APIRouter

from . import autosave, copywriting, crud, download, save, stats

router = APIRouter()

# ⚠️ 注册顺序很重要:
# FastAPI 路由按声明顺序匹配。具体路径必须在带 path param 的通配路径之前注册,
# 否则 /tasks/stats 会被 /tasks/{task_id} 抢先匹配并返回 422 (stats 无法转 int)。
#
# 正确顺序: 精确路径 → path-param 通配路径
router.include_router(save.router)          # POST /tasks/save (精确)
router.include_router(stats.router)         # GET  /tasks/stats, /stats (精确)
router.include_router(copywriting.router)   # /tasks/{id}/copywriting (有额外后缀)
router.include_router(autosave.router)      # /tasks/{id}/autosave (有额外后缀)
router.include_router(download.router)      # /tasks/{id}/download (有额外后缀)
router.include_router(crud.router)          # GET,PUT,DELETE /tasks/{id} (通配,必须最后)

__all__ = ["router"]
