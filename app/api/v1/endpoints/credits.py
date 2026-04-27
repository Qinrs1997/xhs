"""积分与会员 API 聚合路由

已拆分为：
- credits_user.py        积分余额、流水、签到、积分包
- credits_membership.py  会员方案、订阅、取消
- credits_invite.py      邀请码、邀请统计
- credits_admin.py       管理员发放/扣除积分、设置会员
"""
from fastapi import APIRouter

from app.api.v1.endpoints.credits_user import router as user_router
from app.api.v1.endpoints.credits_membership import router as membership_router
from app.api.v1.endpoints.credits_invite import router as invite_router
from app.api.v1.endpoints.credits_admin import router as admin_router

router = APIRouter()
router.include_router(user_router)
router.include_router(membership_router)
router.include_router(invite_router)
router.include_router(admin_router)
