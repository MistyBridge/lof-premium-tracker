"""
交易日历 — 启动时加载到内存，O(1) 查询
加载失败时所有采集任务跳过（宁可不采也不乱采）。
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app")

_calendar: dict[date, bool] = {}
_calendar_loaded: bool = False


async def load_calendar(session: AsyncSession) -> None:
    """启动时加载当年日历到内存"""
    global _calendar, _calendar_loaded
    try:
        year_start = datetime.now(timezone.utc).date().replace(month=1, day=1)
        result = await session.execute(
            text("SELECT trade_date, is_trading FROM trade_calendar WHERE trade_date >= :d"),
            {"d": year_start},
        )
        rows = result.fetchall()
        _calendar = {row[0]: row[1] for row in rows}
        _calendar_loaded = True
        trading_days = sum(1 for v in _calendar.values() if v)
        logger.info("交易日历加载完成: %d 天（其中 %d 个交易日）", len(_calendar), trading_days)
    except Exception:
        _calendar_loaded = False
        logger.critical("交易日历加载失败，所有采集任务将跳过", exc_info=True)


def is_trading_day(target: date | None = None) -> bool:
    """判断是否为交易日，日历未加载时返回 False"""
    if not _calendar_loaded:
        return False
    d = target or datetime.now(timezone.utc).date()
    return _calendar.get(d, False)


def get_latest_trading_date() -> date:
    """获取最近一个交易日（含今天），最多回溯 10 天"""
    today = datetime.now(timezone.utc).date()
    for offset in range(0, 11):
        check = today - timedelta(days=offset)
        if _calendar.get(check, False):
            return check
    return today  # fallback


def is_calendar_loaded() -> bool:
    """日历是否已加载"""
    return _calendar_loaded
