"""自选路由"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from auth.dependencies import get_user_id
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    fund_code: str


@router.get("")
async def list_watchlist(user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    async with hub._sf() as session:
        r = await session.execute(text("SELECT * FROM user_watchlist WHERE user_id=:uid ORDER BY sort_order,created_at"), {"uid": user_id})
        return [dict(x._mapping) for x in r.fetchall()]


@router.post("")
async def add_watchlist(body: WatchlistAdd, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    code = body.fund_code.strip().zfill(6)
    async with hub._sf() as session:
        await session.execute(text("INSERT INTO user_watchlist(user_id,fund_code)VALUES(:uid,:code)ON CONFLICT DO NOTHING"), {"uid": user_id, "code": code})
        await session.commit()
    return {"fund_code": code, "added": True}


@router.delete("/{fund_code}")
async def remove_watchlist(fund_code: str, user_id: str = Depends(get_user_id), hub: ServiceHub = Depends(get_hub)):
    code = fund_code.strip().zfill(6)
    async with hub._sf() as session:
        await session.execute(text("DELETE FROM user_watchlist WHERE user_id=:uid AND fund_code=:code"), {"uid": user_id, "code": code})
        await session.commit()
    return {"deleted": True}
