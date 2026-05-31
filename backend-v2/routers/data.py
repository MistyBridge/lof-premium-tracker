"""日线数据路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("/fund/{code}")
async def fund_daily(
    code: str, fields: Optional[str] = None, from_date: Optional[str] = None,
    to_date: Optional[str] = None, limit: int = Query(60, ge=1, le=1000),
    hub: ServiceHub = Depends(get_hub),
):
    fl = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    return await hub.get_fund_daily(code, fields=fl, from_date=from_date, to_date=to_date, limit=limit)


@router.get("/asset/{code}")
async def asset_daily(
    code: str, fields: Optional[str] = None, from_date: Optional[str] = None,
    to_date: Optional[str] = None, limit: int = Query(60, ge=1, le=1000),
    hub: ServiceHub = Depends(get_hub),
):
    fl = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    return await hub.get_asset_daily(code, fields=fl, from_date=from_date, to_date=to_date, limit=limit)


@router.get("/batch")
async def batch_query(
    codes: str = Query(...), fields: Optional[str] = None,
    from_date: Optional[str] = None, to_date: Optional[str] = None,
    hub: ServiceHub = Depends(get_hub),
):
    cl = [c.strip() for c in codes.split(",") if c.strip()]
    fl = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    return await hub.batch_query(cl, fields=fl, from_date=from_date, to_date=to_date)
