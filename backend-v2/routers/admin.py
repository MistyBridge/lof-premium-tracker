"""管理路由"""
from fastapi import APIRouter, Depends, Query
from auth.dependencies import require_admin
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/monitor")
async def monitor(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_monitor()


@router.get("/diagnose/redis")
async def dr(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_redis()


@router.get("/diagnose/db")
async def dd(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_db()


@router.get("/diagnose/fetcher")
async def df(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_fetcher()


@router.get("/diagnose/queue")
async def dq(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_queue()


@router.get("/diagnose/fund")
async def dfunc(code: str = Query(...), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.diagnose_fund(code)


@router.post("/ops/mv-refresh")
async def mvr(aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.ops_mv_refresh(aid)


@router.post("/ops/cache-clear")
async def cc(pattern: str = Query("*"), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.ops_cache_clear(aid, pattern)


@router.get("/audit-log")
async def al(limit: int = Query(50, ge=1, le=500), aid: str = Depends(require_admin), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_audit_log(limit)
