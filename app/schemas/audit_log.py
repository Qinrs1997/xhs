"""审计日志 Schema"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.models.audit_log import AuditLevel


class AuditLogCreate(BaseModel):
    """创建审计日志"""
    request_id: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    level: str = AuditLevel.MEDIUM.value
    description: Optional[str] = None
    method: str
    path: str
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    detail: Optional[str] = None
    status_code: Optional[int] = None
    response_time: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None


class AuditLogResponse(BaseModel):
    """审计日志响应"""
    id: int
    request_id: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    level: str
    description: Optional[str] = None
    method: str
    path: str
    ip: Optional[str] = None
    detail: Optional[str] = None
    status_code: Optional[int] = None
    response_time: Optional[float] = None
    success: bool
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogList(BaseModel):
    """审计日志列表"""
    total: int
    items: list[AuditLogResponse]


class AuditLogQuery(BaseModel):
    """审计日志查询条件"""
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: Optional[str] = None
    level: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    success: Optional[bool] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
