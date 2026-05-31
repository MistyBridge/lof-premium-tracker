"""
normalize — 多源字段映射 + 类型统一 + 代码清洗
输入: fetcher 原始数据（API 原始字段名）
输出: 统一格式 dict
"""
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional


# ── 类型安全转换 ─────────────────────────────────────────────


def to_optional_float(value) -> Optional[float]:
    """
    安全转浮点。0 不是空值（成交量=0 表示停牌，是有效数据）。
    只有 None、""、"-"、"NaN" 等才返回 None。
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "--", "暂无", "暂无数据", "N/A", "nan", "NaN"):
            return None
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def to_optional_int(value) -> Optional[int]:
    """安全转整数（成交量等）"""
    f = to_optional_float(value)
    return int(f) if f is not None else None


def clean_code(code) -> Optional[str]:
    """基金代码统一清洗: 去空格/逗号/zfill(6)"""
    if code is None:
        return None
    code = str(code).strip().replace(" ", "").replace(",", "")
    code = code.lstrip("0") or "0"
    code = code.zfill(6)
    if not code.isdigit() or len(code) != 6:
        return None
    return code


# ── normalize 函数 ──────────────────────────────────────────


def normalize_realtime(record: dict, source: str = "push2") -> dict:
    """
    统一实时行情格式。
    source: "push2" 或 "tencent"，区分字段映射。
    """
    if source == "tencent":
        return _normalize_realtime_tencent(record)
    return _normalize_realtime_push2(record)


def _calc_float_share_from_turnover(
    volume: Optional[int],
    turnover_rate: Optional[float],
) -> Optional[float]:
    """
    从成交量和换手率反推场内份额（流通份额）。
    float_share(万份) = volume(手) / turnover_rate(%)
    """
    if not volume or not turnover_rate or turnover_rate <= 0:
        return None
    return round(volume / turnover_rate, 2)


def _normalize_realtime_push2(r: dict) -> dict:
    """push2 字段映射: f2=最新价, f3=涨跌幅, f5=成交量, f20=总市值, f21=流通市值"""
    price = to_optional_float(r.get("f2"))
    float_cap = to_optional_float(r.get("f21"))
    volume = to_optional_int(r.get("f5"))
    turnover_rate = to_optional_float(r.get("f8"))

    # 优先: float_share = volume / turnover_rate（成交量+换手率反推）
    # 回退: float_share = 流通市值 / price / 10000
    float_share = _calc_float_share_from_turnover(volume, turnover_rate)
    if float_share is None and float_cap and price and price > 0:
        float_share = round(float_cap / price / 10000, 2)

    return {
        "code": clean_code(r.get("f12")),
        "name": str(r.get("f14") or "").strip(),
        "realtime_price": price,
        "realtime_nav": to_optional_float(r.get("f204")),
        "realtime_amount": to_optional_float(r.get("f6")),
        "volume": volume,
        "change_pct": to_optional_float(r.get("f3")),
        "limit_up": to_optional_float(r.get("f15")),
        "limit_down": to_optional_float(r.get("f16")),
        "turnover_rate": turnover_rate,
        "volume_ratio": to_optional_float(r.get("f10")),
        "outer_volume": to_optional_int(r.get("f32")),
        "inner_volume": to_optional_int(r.get("f33")),
        "prev_close": to_optional_float(r.get("f18")),
        "total_market_cap": to_optional_float(r.get("f20")),
        "float_market_cap": float_cap,
        "float_share": float_share,
        "market": "SH" if str(r.get("f13", "")).startswith("1") else "SZ",
        "is_suspended": volume == 0,
        "fetch_source": "push2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_realtime_tencent(r: dict) -> dict:
    """腾讯 QT 字段映射"""
    return {
        "code": clean_code(r.get("code")),
        "name": str(r.get("name") or "").strip(),
        "realtime_price": to_optional_float(r.get("price")),
        "realtime_nav": None,
        "realtime_amount": to_optional_float(r.get("amount")),
        "volume": to_optional_int(r.get("volume")),
        "change_pct": to_optional_float(r.get("change_pct")),
        "limit_up": None,
        "limit_down": None,
        "turnover_rate": None,
        "volume_ratio": None,
        "outer_volume": None,
        "inner_volume": None,
        "prev_close": to_optional_float(r.get("prev_close")),
        "total_market_cap": None,
        "float_market_cap": None,
        "market": str(r.get("market", "SZ")).upper(),
        "is_suspended": to_optional_int(r.get("volume")) == 0,
        "fetch_source": "tencent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def normalize_nav(record: dict) -> dict:
    """统一净值格式（lsjz 源）"""
    return {
        "code": clean_code(record.get("code")),
        "nav": to_optional_float(record.get("nav")),
        "nav_date": record.get("nav_date"),
        "purchase_status": record.get("purchase_status", "unknown"),
        "redeem_status": record.get("redeem_status", "unknown"),
        "nav_change_pct": to_optional_float(record.get("nav_change_pct")),
    }


def normalize_kline(record: dict, source: str = "push2his") -> dict:
    """统一日线格式"""
    volume = to_optional_int(record.get("volume"))
    turnover_rate = to_optional_float(record.get("turnover_rate"))
    float_share = _calc_float_share_from_turnover(volume, turnover_rate)
    return {
        "code": clean_code(record.get("code")),
        "trade_date": record.get("trade_date"),
        "open": to_optional_float(record.get("open")),
        "high": to_optional_float(record.get("high")),
        "low": to_optional_float(record.get("low")),
        "close": to_optional_float(record.get("close")),
        "volume": volume,
        "amount": to_optional_float(record.get("amount")),
        "change_pct": to_optional_float(record.get("change_pct")),
        "turnover_rate": turnover_rate,
        "float_share": float_share,
    }


def normalize_info(record: dict) -> dict:
    """统一基础信息格式（fundf10 源）"""
    # listing_date: 字符串转 date 对象
    ld = record.get("listing_date")
    if isinstance(ld, str):
        try:
            from datetime import date
            ld = date.fromisoformat(ld)
        except (ValueError, TypeError):
            ld = None

    return {
        "code": clean_code(record.get("code")),
        "name": record.get("name"),
        "purchase_fee_rate": to_optional_float(record.get("purchase_fee_rate")),
        "redemption_fee_rate": to_optional_float(record.get("redemption_fee_rate")),
        "purchase_limit": to_optional_float(record.get("purchase_limit")),
        "purchase_status": record.get("purchase_status"),
        "redeem_status": record.get("redeem_status"),
        "holdings": record.get("holdings") or [],
        "holding_quarter": record.get("holding_quarter"),
        "fund_type": record.get("fund_type"),
        "index_code": record.get("index_code"),
        "aum": to_optional_float(record.get("aum")),
        "listing_date": ld,
        "redeem_days": to_optional_int(record.get("redeem_days")),
        "qdii_quota_status": record.get("qdii_quota_status", "open"),
        "market": record.get("market"),
    }
