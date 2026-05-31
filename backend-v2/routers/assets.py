"""资产路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


@router.get("")
async def list_assets(
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None, asset_type: Optional[str] = None,
    hub: ServiceHub = Depends(get_hub),
):
    return await hub.get_asset_list(page=page, size=size, search=search, asset_type=asset_type)


@router.get("/{code}")
async def asset_detail(code: str, hub: ServiceHub = Depends(get_hub)):
    return await hub.get_asset_detail(code)


@router.get("/{code}/funds")
async def asset_funds(code: str, hub: ServiceHub = Depends(get_hub)):
    return await hub.get_asset_funds(code)


@router.get("/{code}/chart")
async def asset_chart(code: str, days: int = Query(30, ge=1, le=365), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_asset_chart(code, days)
