"""基金路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from auth.dependencies import get_optional_user
from constants import (
    PROFIT_COMMISSION_MIN,
    PROFIT_COMMISSION_RATE,
    PROFIT_MAX_CAPITAL,
)
from hub import get_hub
from hub.service import ServiceHub

router = APIRouter(prefix="/api/v1/funds", tags=["funds"])


@router.get("")
async def list_funds(
    page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=1500),
    sort: str = Query("amount"), order: str = Query("desc"),
    search: Optional[str] = None, fund_type: Optional[str] = None,
    premium_min: Optional[float] = None, premium_max: Optional[float] = None,
    amount_min: Optional[float] = None, amount_max: Optional[float] = None,
    turnover_min: Optional[float] = None, filter_mode: Optional[str] = None,
    user_id: Optional[str] = Depends(get_optional_user),
    hub: ServiceHub = Depends(get_hub),
):
    return await hub.get_fund_list(
        page=page, size=size, sort=sort, order=order, search=search,
        fund_type=fund_type, premium_min=premium_min, premium_max=premium_max,
        amount_min=amount_min, amount_max=amount_max, turnover_min=turnover_min,
        filter_mode=filter_mode, user_id=user_id,
    )


@router.get("/batch")
async def batch_funds(codes: str = Query(...), hub: ServiceHub = Depends(get_hub)):
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    return await hub.get_fund_batch(code_list)


@router.get("/rankings")
async def rankings(hub: ServiceHub = Depends(get_hub)):
    return await hub.get_fund_list(page=1, size=50, sort="premium_rate", order="desc")


@router.get("/{code}")
async def fund_detail(code: str, hub: ServiceHub = Depends(get_hub)):
    return await hub.get_fund_detail(code)


@router.get("/{code}/chart")
async def fund_chart(code: str, days: int = Query(30, ge=1, le=365), hub: ServiceHub = Depends(get_hub)):
    return await hub.get_fund_chart(code, days)


@router.get("/{code}/profit")
async def fund_profit(
    code: str,
    commission_rate: float = Query(PROFIT_COMMISSION_RATE, ge=0),
    commission_min: float = Query(PROFIT_COMMISSION_MIN, ge=0),
    max_capital: float = Query(PROFIT_MAX_CAPITAL, gt=0),
    hub: ServiceHub = Depends(get_hub),
):
    return await hub.calc_profit(
        code,
        commission_rate=commission_rate,
        commission_min=commission_min,
        max_capital=max_capital,
    )


@router.get("/{code}/holdings")
async def fund_holdings(code: str, hub: ServiceHub = Depends(get_hub)):
    return await hub.get_fund_holdings(code)


@router.get("/{code}/est_nav")
async def fund_est_nav(code: str, hub: ServiceHub = Depends(get_hub)):
    return await hub.get_fund_est_nav(code)
