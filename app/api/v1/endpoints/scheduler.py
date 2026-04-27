"""定时任务管理 API

提供任务的增删改查、执行日志查看等功能。
仅管理员可访问。
"""
from typing import Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_current_superuser
from app.core.scheduler import scheduler
from app.core.exceptions import NotFoundError, BadRequestError
from app.schemas.response import Response
from app.models.user import User as UserModel

router = APIRouter()


# ==================== Schemas ====================

class JobCreate(BaseModel):
    """创建任务请求"""
    id: Optional[str] = Field(None, description="任务ID，不填则自动生成")
    name: str = Field(..., description="任务名称")
    description: str = Field("", description="任务描述")
    trigger: str = Field(..., description="触发器类型: cron, interval, date")

    # Cron 触发器参数
    hour: Optional[int] = Field(None, ge=0, le=23, description="小时 (0-23)")
    minute: Optional[int] = Field(None, ge=0, le=59, description="分钟 (0-59)")
    second: Optional[int] = Field(None, ge=0, le=59, description="秒 (0-59)")
    day_of_week: Optional[int] = Field(None, ge=0, le=6, description="星期几 (0=周一)")

    # Interval 触发器参数
    days: Optional[int] = Field(None, ge=0, description="间隔天数")
    hours: Optional[int] = Field(None, ge=0, description="间隔小时")
    minutes: Optional[int] = Field(None, ge=0, description="间隔分钟")
    seconds: Optional[int] = Field(None, ge=0, description="间隔秒数")

    # Date 触发器参数
    run_date: Optional[datetime] = Field(None, description="执行时间")

    # 任务函数（通过名称引用已注册的函数）
    task_func: str = Field(..., description="任务函数名称（需要预先注册）")


class JobResponse(BaseModel):
    """任务信息响应"""
    id: str
    name: str
    func_name: str
    trigger_type: str
    trigger_args: dict
    status: str
    next_run_time: Optional[str]
    last_run_time: Optional[str]
    last_result: Optional[str]
    run_count: int
    error_count: int
    created_at: str
    description: str
    is_system: bool = False


class JobUpdate(BaseModel):
    """修改任务请求"""
    name: Optional[str] = Field(None, description="任务名称")
    description: Optional[str] = Field(None, description="任务描述")
    trigger: Optional[str] = Field(None, description="触发器类型: cron, interval, date")

    # Cron 触发器参数
    hour: Optional[int] = Field(None, ge=0, le=23, description="小时 (0-23)")
    minute: Optional[int] = Field(None, ge=0, le=59, description="分钟 (0-59)")
    second: Optional[int] = Field(None, ge=0, le=59, description="秒 (0-59)")
    day_of_week: Optional[int] = Field(None, ge=0, le=6, description="星期几 (0=周一)")

    # Interval 触发器参数
    days: Optional[int] = Field(None, ge=0, description="间隔天数")
    hours: Optional[int] = Field(None, ge=0, description="间隔小时")
    minutes: Optional[int] = Field(None, ge=0, description="间隔分钟")
    seconds: Optional[int] = Field(None, ge=0, description="间隔秒数")

    # Date 触发器参数
    run_date: Optional[datetime] = Field(None, description="执行时间")


class JobListResponse(BaseModel):
    """任务列表响应"""
    total: int
    items: list[JobResponse]


class SchedulerStatsResponse(BaseModel):
    """调度器统计响应"""
    is_running: bool
    total_jobs: int
    running_jobs: int
    paused_jobs: int
    total_executions: int
    total_errors: int


class JobLogResponse(BaseModel):
    """任务日志响应"""
    job_id: str
    started_at: str
    finished_at: Optional[str]
    status: str
    result: Optional[str]
    error: Optional[str]
    duration_ms: Optional[float]


# ==================== 注册的任务函数 ====================

# 存储可以通过 API 调用的任务函数
_registered_task_funcs: dict[str, callable] = {}


def register_task_func(name: str, func: callable):
    """注册任务函数，使其可以通过 API 创建任务"""
    _registered_task_funcs[name] = func


def get_task_func(name: str) -> Optional[callable]:
    """获取已注册的任务函数"""
    return _registered_task_funcs.get(name)


# ==================== API 端点 ====================


def _build_job_response(j) -> JobResponse:
    """从 JobInfo 构建 JobResponse（避免重复代码）"""
    return JobResponse(
        id=j.id,
        name=j.name,
        func_name=j.func_name,
        trigger_type=j.trigger_type.value,
        trigger_args=j.trigger_args,
        status=j.status.value,
        next_run_time=j.next_run_time.isoformat() if j.next_run_time else None,
        last_run_time=j.last_run_time.isoformat() if j.last_run_time else None,
        last_result=j.last_result,
        run_count=j.run_count,
        error_count=j.error_count,
        created_at=j.created_at.isoformat(),
        description=j.description,
        is_system=j.is_system,
    )


@router.get("/stats", response_model=Response[SchedulerStatsResponse], summary="获取调度器统计")
async def get_scheduler_stats(
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取调度器统计信息"""
    stats = scheduler.stats()
    return Response(
        code=200,
        message="获取成功",
        data=SchedulerStatsResponse(**stats)
    )


@router.get("/jobs", response_model=Response[JobListResponse], summary="获取任务列表")
async def get_jobs(
    status: Optional[str] = Query(None, description="按状态筛选"),
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取所有定时任务"""
    jobs = scheduler.get_jobs()

    # 筛选
    if status:
        jobs = [j for j in jobs if j.status.value == status]

    items = [
        _build_job_response(j)
        for j in jobs
    ]

    return Response(
        code=200,
        message="获取成功",
        data=JobListResponse(total=len(items), items=items)
    )


@router.get("/jobs/{job_id}", response_model=Response[JobResponse], summary="获取任务详情")
async def get_job(
    job_id: str,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取指定任务详情"""
    job = scheduler.get_job(job_id)
    if not job:
        raise NotFoundError(f"任务不存在: {job_id}")

    return Response(
        code=200,
        message="获取成功",
        data=_build_job_response(job)
    )


@router.post("/jobs", response_model=Response[JobResponse], summary="创建任务")
async def create_job(
    job_in: JobCreate,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """
    创建定时任务

    注意：task_func 必须是预先注册的函数名称
    """
    # 获取任务函数
    task_func = get_task_func(job_in.task_func)
    if not task_func:
        raise BadRequestError(f"任务函数未注册: {job_in.task_func}")

    # 构建触发器参数
    trigger_args = {}

    if job_in.trigger == "cron":
        if job_in.hour is not None:
            trigger_args["hour"] = job_in.hour
        if job_in.minute is not None:
            trigger_args["minute"] = job_in.minute
        if job_in.second is not None:
            trigger_args["second"] = job_in.second
        if job_in.day_of_week is not None:
            trigger_args["day_of_week"] = job_in.day_of_week

    elif job_in.trigger == "interval":
        if job_in.days:
            trigger_args["days"] = job_in.days
        if job_in.hours:
            trigger_args["hours"] = job_in.hours
        if job_in.minutes:
            trigger_args["minutes"] = job_in.minutes
        if job_in.seconds:
            trigger_args["seconds"] = job_in.seconds

        if not trigger_args:
            raise BadRequestError("间隔任务需要指定至少一个间隔参数")

    elif job_in.trigger == "date":
        if not job_in.run_date:
            raise BadRequestError("一次性任务需要指定执行时间")
        trigger_args["run_date"] = job_in.run_date

    else:
        raise BadRequestError(f"不支持的触发器类型: {job_in.trigger}")

    # 创建任务
    job = await scheduler.add_job(
        func=task_func,
        trigger=job_in.trigger,
        id=job_in.id,
        name=job_in.name,
        description=job_in.description,
        **trigger_args
    )

    return Response(
        code=200,
        message="创建成功",
        data=_build_job_response(job)
    )


@router.put("/jobs/{job_id}", response_model=Response[JobResponse], summary="修改任务配置")
async def update_job(
    job_id: str,
    job_in: JobUpdate,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """
    修改任务的调度配置

    支持修改：任务名称、描述、触发类型、调度时间参数。
    系统内置任务也可修改调度时间。
    """
    job = scheduler.get_job(job_id)
    if not job:
        raise NotFoundError(f"任务不存在: {job_id}")

    # 构建触发器参数（仅当传了触发器相关字段时才更新）
    trigger_type = job_in.trigger or job.trigger_type.value
    trigger_args = None

    if trigger_type == "cron":
        # 构建新的 cron 参数（未传的字段保留原值）
        new_args = dict(job.trigger_args) if not job_in.trigger else {}
        if job_in.hour is not None:
            new_args["hour"] = job_in.hour
        if job_in.minute is not None:
            new_args["minute"] = job_in.minute
        if job_in.second is not None:
            new_args["second"] = job_in.second
        if job_in.day_of_week is not None:
            new_args["day_of_week"] = job_in.day_of_week
        if new_args != job.trigger_args:
            trigger_args = new_args

    elif trigger_type == "interval":
        new_args = dict(job.trigger_args) if not job_in.trigger else {}
        if job_in.days is not None:
            new_args["days"] = job_in.days
        if job_in.hours is not None:
            new_args["hours"] = job_in.hours
        if job_in.minutes is not None:
            new_args["minutes"] = job_in.minutes
        if job_in.seconds is not None:
            new_args["seconds"] = job_in.seconds
        if not new_args:
            raise BadRequestError("间隔任务需要指定至少一个间隔参数")
        if new_args != job.trigger_args:
            trigger_args = new_args

    elif trigger_type == "date":
        if job_in.run_date:
            trigger_args = {"run_date": job_in.run_date}

    # 调用调度器更新
    updated = await scheduler.update_job(
        job_id,
        name=job_in.name,
        description=job_in.description,
        trigger=job_in.trigger,
        trigger_args=trigger_args,
    )

    return Response(
        code=200,
        message="修改成功",
        data=_build_job_response(updated)
    )


@router.delete("/jobs/{job_id}", response_model=Response[None], summary="删除任务")
async def delete_job(
    job_id: str,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """删除指定任务（系统内置任务不可删除）"""
    job = scheduler.get_job(job_id)
    if not job:
        raise NotFoundError(f"任务不存在: {job_id}")
    if job.is_system:
        raise BadRequestError("系统内置任务不可删除，可以暂停或修改调度时间")
    success = await scheduler.remove_job(job_id)
    if not success:
        raise NotFoundError(f"任务不存在: {job_id}")

    return Response(code=200, message="删除成功")


@router.post("/jobs/{job_id}/pause", response_model=Response[None], summary="暂停任务")
async def pause_job(
    job_id: str,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """暂停指定任务"""
    success = await scheduler.pause_job(job_id)
    if not success:
        raise NotFoundError(f"任务不存在: {job_id}")

    return Response(code=200, message="暂停成功")


@router.post("/jobs/{job_id}/resume", response_model=Response[None], summary="恢复任务")
async def resume_job(
    job_id: str,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """恢复指定任务"""
    success = await scheduler.resume_job(job_id)
    if not success:
        raise NotFoundError(f"任务不存在: {job_id}")

    return Response(code=200, message="恢复成功")


@router.post("/jobs/{job_id}/run", response_model=Response[None], summary="立即执行任务")
async def run_job(
    job_id: str,
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """立即执行指定任务"""
    success = await scheduler.run_job_now(job_id)
    if not success:
        raise NotFoundError(f"任务不存在或正在执行中: {job_id}")

    return Response(code=200, message="任务已触发")


@router.get("/jobs/{job_id}/logs", response_model=Response[list[JobLogResponse]], summary="获取任务执行日志")
async def get_job_logs(
    job_id: str,
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取指定任务的执行日志"""
    logs = scheduler.get_job_logs(job_id=job_id, limit=limit)

    return Response(
        code=200,
        message="获取成功",
        data=[JobLogResponse(**log) for log in logs]
    )


@router.get("/logs", response_model=Response[list[JobLogResponse]], summary="获取所有执行日志")
async def get_all_logs(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取所有任务的执行日志"""
    logs = scheduler.get_job_logs(limit=limit)

    return Response(
        code=200,
        message="获取成功",
        data=[JobLogResponse(**log) for log in logs]
    )


@router.get("/funcs", response_model=Response[list[str]], summary="获取可用任务函数")
async def get_available_funcs(
    current_user: UserModel = Depends(get_current_superuser)
) -> Any:
    """获取已注册的可用任务函数列表"""
    return Response(
        code=200,
        message="获取成功",
        data=list(_registered_task_funcs.keys())
    )
