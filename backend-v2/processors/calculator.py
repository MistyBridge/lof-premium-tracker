"""
calculator — 派生字段计算
溢价率 / 盘中溢价率 / 三日均溢 / 换手率 / 涨跌幅 / 预计收益率
所有入口调用 to_float 保证 Decimal 不混入计算，结果 round(value, 4)。
"""
from decimal import Decimal
from typing import Optional

from processors.normalize import to_optional_float


# ── 类型转换 ────────────────────────────────────────────────


def to_float(value) -> Optional[float]:
    """统一转 float，处理 Decimal/int/str"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def to_int(value) -> Optional[int]:
    """统一转 int"""
    f = to_float(value)
    return int(f) if f is not None else None


# ── 计算函数 ────────────────────────────────────────────────


def calc_premium_rate(close: Optional[float], nav: Optional[float]) -> Optional[float]:
    """溢价率 = (close - nav) / nav * 100"""
    if close is None or nav is None or nav <= 0:
        return None
    return round((close - nav) / nav * 100, 4)


def calc_realtime_premium(
    price: Optional[float],
    realtime_nav: Optional[float],
) -> Optional[float]:
    """盘中溢价率 = (price - realtime_nav) / realtime_nav * 100"""
    if price is None or realtime_nav is None or realtime_nav <= 0:
        return None
    return round((price - realtime_nav) / realtime_nav * 100, 4)


def calc_premium_3d(recent_daily: list[dict]) -> Optional[float]:
    """三日均溢 = 近3个交易日收盘溢价率算术平均"""
    rates = [
        d.get("premium_rate") for d in recent_daily[-3:]
        if d.get("premium_rate") is not None
    ]
    if not rates:
        return None
    return round(sum(rates) / len(rates), 4)


def calc_float_share(
    volume: Optional[int],
    turnover_rate: Optional[float],
) -> Optional[float]:
    """
    从成交量和换手率反推场内份额（流通份额）。
    float_share(万份) = volume(手) / turnover_rate(%)
    推导: turnover_rate(%) = volume(手)*100 / float_share(万份)/10000 * 100
    """
    if not volume or not turnover_rate or turnover_rate <= 0:
        return None
    return round(volume / turnover_rate, 2)


def calc_turnover_rate(
    volume: Optional[float],
    float_share: Optional[float],
    raw_turnover_rate: Optional[float] = None,
) -> Optional[float]:
    """
    换手率：优先使用数据源原值，缺失时从 volume/float_share 重算。
    volume: 手 (1手=100份), float_share: 万份
    """
    if raw_turnover_rate is not None and raw_turnover_rate > 0:
        return round(raw_turnover_rate, 4)
    if not volume or not float_share or float_share <= 0:
        return None
    float_share_in_shares = float_share * 10000
    turnover = volume * 100 / float_share_in_shares * 100
    return round(turnover, 4)


def calc_change_pct(
    close: Optional[float],
    prev_close: Optional[float],
) -> Optional[float]:
    """涨跌幅 = (close - prev_close) / prev_close * 100"""
    if close is None or prev_close is None or prev_close <= 0:
        return None
    return round((close - prev_close) / prev_close * 100, 4)


def calc_est_return(
    premium_rate: Optional[float],
    purchase_fee_rate: Optional[float],
    redemption_fee_rate: Optional[float],
    commission: float = 0.0001,
    fee_discount: float = 1.0,
) -> Optional[float]:
    """
    预计收益率（用户参数化）
    溢价套利: premium/100 - p_fee*discount - r_fee - commission*2
    折价套利: |premium|/100 - p_fee - r_fee - commission*2
    """
    if premium_rate is None:
        return None
    if redemption_fee_rate is None:
        return None  # 赎回费率未知时无法估算收益

    p_fee = (to_float(purchase_fee_rate) or 0) * fee_discount / 100
    r_fee = to_float(redemption_fee_rate) / 100

    if premium_rate > 0:
        net = premium_rate / 100 - p_fee - r_fee - commission * 2
    else:
        net = abs(premium_rate) / 100 - p_fee - r_fee - commission * 2

    return round(net * 100, 2)


# ── daily_save 组合计算 ─────────────────────────────────────


async def calc_daily_fields(
    fund: dict,
    prev_day: Optional[dict],
    recent_3d: list[dict],
) -> dict:
    """
    daily_save 主计算函数。
    输入全部预加载的数据，不在函数内查询 DB。
    float_share 优先从数据源 turnover_rate 反推，缺失时保留原值。
    """
    close = to_float(fund.get("close"))
    nav = to_float(fund.get("nav"))
    prev_close = to_float(prev_day.get("close")) if prev_day else None
    volume = to_int(fund.get("volume"))
    raw_turnover_rate = to_float(fund.get("turnover_rate"))

    # float_share: 优先用 volume/turnover_rate 反推，缺失时保留原值
    float_share = calc_float_share(volume, raw_turnover_rate)
    if float_share is None:
        float_share = to_float(fund.get("float_share"))

    # turnover_rate: 优先用数据源原值，缺失时从 volume/float_share 重算
    turnover_rate = calc_turnover_rate(volume, float_share, raw_turnover_rate)

    return {
        "code": fund["code"],
        "trade_date": fund["trade_date"],
        "open": to_float(fund.get("open")),
        "high": to_float(fund.get("high")),
        "low": to_float(fund.get("low")),
        "close": close,
        "volume": volume,
        "amount": to_float(fund.get("amount")),
        "nav": nav,
        "nav_date": fund.get("nav_date"),
        "nav_type": fund.get("nav_type", "confirmed"),
        "nav_source": fund.get("nav_source", "lsjz"),
        "premium_rate": calc_premium_rate(close, nav),
        "turnover_rate": turnover_rate,
        "change_pct": calc_change_pct(close, prev_close),
        "float_share": float_share,
        "total_share": to_float(fund.get("total_share")),
        "data_source": fund.get("fetch_source", "push2"),
        "fetch_batch_id": fund.get("fetch_batch_id"),
    }
