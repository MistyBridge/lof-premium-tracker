"""
响应 Pydantic 模型 — 13 个模型
统一格式: {code: 0, data: ..., meta: ..., message: "success"}
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── 分页元信息 ──────────────────────────────────────────────


class PaginatedMeta(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int
    data_timestamp: Optional[str] = None
    data_type: Optional[str] = None  # "realtime" / "closing"
    latest_trading_date: Optional[str] = None
    realtime_available: Optional[bool] = None
    snapshot_date: Optional[str] = None
    ignored_fields: Optional[list[str]] = None


# ── 统一响应封装 ────────────────────────────────────────────


class ApiResponse(BaseModel):
    code: int = 0
    data: Any = None
    meta: Any = None
    message: str = "success"


def ok(data: Any = None, meta: Any = None, message: str = "success") -> dict:
    """成功响应"""
    resp = {"code": 0, "message": message}
    if data is not None:
        resp["data"] = data
    if meta is not None:
        resp["meta"] = meta
    return resp


# ── 基金 ────────────────────────────────────────────────────


class FundListItem(BaseModel):
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    market: Optional[str] = None
    close: Optional[float] = None
    nav: Optional[float] = None
    premium_rate: Optional[float] = None
    change_pct: Optional[float] = None
    amount: Optional[float] = None
    volume: Optional[int] = None
    turnover_rate: Optional[float] = None
    float_share: Optional[float] = None
    aum: Optional[float] = None
    realtime_price: Optional[float] = None
    realtime_nav: Optional[float] = None


class FundDetail(BaseModel):
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    market: Optional[str] = None
    close: Optional[float] = None
    nav: Optional[float] = None
    premium_rate: Optional[float] = None
    change_pct: Optional[float] = None
    amount: Optional[float] = None
    volume: Optional[int] = None
    turnover_rate: Optional[float] = None
    float_share: Optional[float] = None
    aum: Optional[float] = None
    purchase_fee_rate: Optional[float] = None
    redemption_fee_rate: Optional[float] = None
    purchase_limit: Optional[float] = None
    purchase_status: Optional[str] = None
    redeem_status: Optional[str] = None
    holdings: Optional[list] = None
    holding_quarter: Optional[str] = None
    realtime_price: Optional[float] = None
    realtime_nav: Optional[float] = None


class FundChartPoint(BaseModel):
    trade_date: date
    close: Optional[float] = None
    nav: Optional[float] = None
    premium_rate: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    change_pct: Optional[float] = None


# ── 资产 ────────────────────────────────────────────────────


class AssetListItem(BaseModel):
    code: str
    name: Optional[str] = None
    asset_type: Optional[str] = None
    market: Optional[str] = None


class AssetDetail(BaseModel):
    code: str
    name: Optional[str] = None
    asset_type: Optional[str] = None
    market: Optional[str] = None
    updated_at: Optional[datetime] = None


# ── 日线 ────────────────────────────────────────────────────


class DailyRow(BaseModel):
    trade_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    nav: Optional[float] = None
    premium_rate: Optional[float] = None
    turnover_rate: Optional[float] = None
    change_pct: Optional[float] = None


# ── 公式 ────────────────────────────────────────────────────


class Formula(BaseModel):
    id: int
    user_id: str
    group_id: Optional[int] = None
    name: str
    expression: str
    description: Optional[str] = None
    sort_order: int = 0
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FormulaGroup(BaseModel):
    id: int
    user_id: str
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── 预警 ────────────────────────────────────────────────────


class Alert(BaseModel):
    id: int
    user_id: str
    name: str
    fund_code: Optional[str] = None
    condition: dict
    is_active: bool = True
    last_triggered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── 系统 ────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    version: str = "2.0.0"
    database: Optional[str] = None
    redis: Optional[str] = None
    latest_data_date: Optional[str] = None
    timestamp: Optional[str] = None


class SystemMonitor(BaseModel):
    fetch_status: dict = {}
    api_requests: int = 0
    db_query_avg_ms: float = 0
    cache_hit_rate: float = 0
    memory_mb: float = 0
    disk_usage_pct: float = 0


# ── SSE ─────────────────────────────────────────────────────


class SSEEvent(BaseModel):
    type: str
    ts: str
    changes: Optional[list] = None
    message: Optional[str] = None


# ── 错误 ────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    code: int
    message: str
    detail: Any = None
