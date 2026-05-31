"""
validator — 校验 + 去重 + 涨跌停标记 + 异常检测
异常标记不丢弃（除非数据无效），保证数据完整性。
"""
import logging
from datetime import date, timedelta

from constants import NAV_JUMP_CRITICAL, PRICE_DEVIATION_WARN, PRICE_CHANGE_WARN

logger = logging.getLogger("fetcher")


# ── 校验函数 ────────────────────────────────────────────────


def validate_realtime(record: dict) -> dict:
    """
    实时行情校验。
    price <= 0 标记异常但保留（可能停牌），code 无效丢弃。
    """
    code = record.get("code")
    if not code or len(code) != 6 or not code.isdigit():
        return {}

    price = record.get("realtime_price")
    if price is not None and price <= 0:
        record["risk_warning"] = "price_zero"

    change = record.get("change_pct")
    if change is not None and abs(change) > PRICE_CHANGE_WARN:
        record["risk_warning"] = "change_abnormal"

    return record


def validate_nav(record: dict) -> dict | None:
    """
    净值校验。nav <= 0 或 nav_date 无效 → 丢弃。
    """
    if not record.get("code"):
        return None

    nav = record.get("nav")
    if nav is None or nav <= 0:
        return None

    nav_date = record.get("nav_date")
    if not nav_date:
        return None

    return record


def validate_kline(record: dict) -> dict | None:
    """
    日线校验。close <= 0 或 trade_date 无效 → 丢弃。
    """
    if not record.get("code"):
        return None

    close = record.get("close")
    if close is None or close <= 0:
        return None

    if not record.get("trade_date"):
        return None

    volume = record.get("volume")
    if volume is not None and volume < 0:
        return None

    return record


def validate_info(record: dict) -> dict | None:
    """
    基础信息校验。code 缺失 → 丢弃，费率解析失败保留 None。
    """
    if not record.get("code"):
        return None
    return record


# ── 涨跌停标记 ──────────────────────────────────────────────


def mark_limit_status(record: dict) -> dict:
    """价格触及涨跌停 → risk_warning"""
    price = record.get("realtime_price") or record.get("close")
    limit_up = record.get("limit_up")
    limit_down = record.get("limit_down")

    if price and limit_up and abs(price - limit_up) < 0.001:
        record["risk_warning"] = "涨停标的"
    elif price and limit_down and abs(price - limit_down) < 0.001:
        record["risk_warning"] = "跌停标的"

    return record


# ── 去重 ────────────────────────────────────────────────────


def deduplicate(records: list[dict], key: str = "code") -> list[dict]:
    """同 key 多条 → 取最后一条（最新）"""
    seen: dict[str, dict] = {}
    for r in records:
        k = r.get(key)
        if k:
            seen[k] = r
    return list(seen.values())


# ── 异常检测 ────────────────────────────────────────────────


async def detect_anomalies(
    records: list[dict],
    history_map: dict[str, list[dict]],
) -> list[dict]:
    """
    历史对比异常检测。
    history_map: {code: [近20日记录]}，批量预加载，不在函数内查询。
    """
    for record in records:
        code = record.get("code")
        history = history_map.get(code, [])
        if len(history) < 5:
            continue

        # 收盘价偏离 20 日均值 > 30%
        close = record.get("close")
        if close and history:
            closes = [h["close"] for h in history if h.get("close")]
            if closes:
                avg_close = sum(closes) / len(closes)
                if avg_close > 0:
                    deviation = abs(close - avg_close) / avg_close * 100
                    if deviation > PRICE_DEVIATION_WARN:
                        record["risk_warning"] = "price_anomaly"

        # 净值突变 > 80%
        nav = record.get("nav")
        if nav and history:
            last_nav = history[-1].get("nav")
            if last_nav and last_nav > 0:
                nav_change = abs(nav - last_nav) / last_nav * 100
                if nav_change > NAV_JUMP_CRITICAL:
                    record["risk_warning"] = "nav_jump"

    return records
