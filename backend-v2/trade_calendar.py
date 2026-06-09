"""
交易日历 — 启动时加载到内存，O(1) 查询
加载失败时自动重试（最多3次），失败后所有采集任务跳过。
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app")

_calendar: dict[date, bool] = {}
_calendar_loaded: bool = False


async def load_calendar(session: AsyncSession, max_retries: int = 3) -> None:
    """启动时加载当年日历到内存，失败自动重试"""
    global _calendar, _calendar_loaded
    for attempt in range(1, max_retries + 1):
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
            return
        except Exception:
            _calendar_loaded = False
            if attempt < max_retries:
                wait = attempt * 2
                logger.warning("交易日历加载失败 (第%d次)，%ds后重试...", attempt, wait)
                await asyncio.sleep(wait)
            else:
                logger.critical("交易日历加载失败（%d次重试均失败），所有采集任务将跳过", max_retries, exc_info=True)


async def reload_calendar(session) -> None:
    """定期重新加载日历（用于运行中恢复）"""
    global _calendar_loaded
    if _calendar_loaded:
        return  # 已加载，不需要重试
    logger.info("[CALENDAR] 尝试重新加载交易日历...")
    await load_calendar(session)


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
