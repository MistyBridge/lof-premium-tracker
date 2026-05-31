"""系统路由"""
from fastapi import APIRouter, Depends
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(tags=["system"])


@router.get("/api/v1/health")
async def health(hub: ServiceHub = Depends(get_hub)):
    return await hub.get_health()
