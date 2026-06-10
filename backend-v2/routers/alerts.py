"""预警路由"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from auth.dependencies import get_user_id
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


class AlertCreate(BaseModel):
    name: str
    fund_code: Optional[str] = None
    condition: dict
    email: Optional[str] = None


class AlertToggle(BaseModel):
    is_active: bool


@router.get("")
async def list_alerts(user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.list_alerts(user_id)


@router.post("")
async def create_alert(body: AlertCreate, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.create_alert(user_id, body.model_dump())


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    await hub.delete_alert(user_id, alert_id)
    return {"deleted": True}


@router.put("/{alert_id}/toggle")
async def toggle_alert(alert_id: int, body: AlertToggle, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    return await hub.toggle_alert(user_id, alert_id, body.is_active)
