"""APScheduler - M7 调度层"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from config import settings
import database
from metrics import alert


def _sf():
    """运行时获取 session factory（避免 import 时绑定 None）"""
    return database.async_session_factory
from mq import publish_event
from trade_calendar import is_trading_day

logger = logging.getLogger("app")
scheduler = None
_failures = {}
_http_client: httpx.AsyncClient | None = None


async def init_scheduler_http() -> None:
    global _http_client
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10),
    )


async def close_scheduler_http() -> None:
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None

def create_scheduler():
    global scheduler
    scheduler = AsyncIOScheduler(job_defaults={"max_instances":1,"coalesce":True,"misfire_grace_time":300}, timezone="Asia/Shanghai")
    scheduler.add_job(job_scan_codes, CronTrigger(day_of_week="mon", hour=8, minute=30), id="scan_codes")
    scheduler.add_job(job_fetch_info, CronTrigger(day_of_week="mon-fri", hour=9, minute=0), id="fetch_info")
    scheduler.add_job(job_fetch_realtime, IntervalTrigger(minutes=5), id="fetch_realtime")
    scheduler.add_job(job_fetch_nav, CronTrigger(hour=20, minute=0), id="fetch_nav")
    scheduler.add_job(job_fetch_kline, CronTrigger(hour=20, minute=30), id="fetch_kline")
    scheduler.add_job(job_fetch_nav_qdii, CronTrigger(hour=23, minute=0), id="fetch_nav_qdii")
    scheduler.add_job(job_daily_save, CronTrigger(hour=23, minute=30), id="daily_save")
    scheduler.add_job(job_check_partitions, CronTrigger(day=1, hour=9, minute=0), id="check_partitions")
    scheduler.add_job(job_check_calendar, CronTrigger(month=12, day=1, hour=9, minute=0), id="check_calendar")
    return scheduler

async def check_and_catchup() -> None:
    if not scheduler:
        return
    logger.info("[SCHEDULER] checking catchup...")
    now = datetime.now()
    for job in scheduler.get_jobs():
        try:
            nr = job.trigger.get_next_fire_time(None, now)
            if nr and nr.date() == now.date() and nr < now:
                if not await _has_success(job.id):
                    job.modify(next_run_time=now)
        except Exception:
            pass

async def _has_success(jid: str) -> bool:
    try:
        async with _sf() as session:
            result = await session.execute(text(
                "SELECT count(*) FROM job_log "
                "WHERE job_name=:jid AND status='success' "
                "AND date(created_at)=current_date"
            ), {"jid": jid})
            return result.scalar() > 0
    except Exception:
        return False

def _ok(jid, ms, n=0):
    _failures[jid] = 0
    logger.info("[JOB] %s ok %.0fms %d", jid, ms, n)
    asyncio.create_task(_log(jid, "success", ms, n))

def _fail(jid, e):
    _failures[jid] = _failures.get(jid, 0) + 1
    c = _failures[jid]
    logger.error("[JOB] %s fail #%d: %s", jid, c, e)
    asyncio.create_task(_log(jid, "failed", err=str(e)))
    if c >= 3:
        asyncio.create_task(alert(title=jid+" failed", message=str(e), level="P1", webhook_url=settings.ALERT_WEBHOOK_URL))

async def _log(jid: str, st: str, ms: float = 0,
               n: int = 0, err: str = "") -> None:
    try:
        async with _sf() as session:
            await session.execute(text(
                "INSERT INTO job_log"
                "(job_name,status,duration_ms,records,error_msg,created_at) "
                "VALUES(:jid,:st,:ms,:n,:err,NOW())"
            ), {"jid": jid, "st": st, "ms": ms, "n": n, "err": err})
            await session.commit()
    except Exception:
        pass

async def job_scan_codes() -> None:
    s = time.monotonic()
    try:
        from fetchers.realtime import _fetch_push2_realtime
        d = await _fetch_push2_realtime(_http_client)
        if not d:
            raise ValueError("no data")
        await publish_event("scan_codes", {
            "data": [{"code": x.get("code"), "name": x.get("f14")} for x in d]
        })
        _ok("scan_codes", (time.monotonic() - s) * 1000, len(d))
    except Exception as e:
        _fail("scan_codes", e)


async def job_fetch_info() -> None:
    s = time.monotonic()
    try:
        from fetchers.info import fetch_info
        codes = await _codes()
        if not codes:
            return
        r = await fetch_info(_http_client, codes)
        _ok("fetch_info", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_info", e)


async def job_fetch_realtime() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.realtime import fetch_realtime
        r = await fetch_realtime(_http_client)
        _ok("fetch_realtime", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_realtime", e)

    # 停牌状态更新（伴随每次5分钟快照）
    try:
        from database import async_session_factory
        from processors.suspension import batch_update_suspension
        await batch_update_suspension(async_session_factory)
    except Exception as e:
        logger.warning("[SCHEDULER] 停牌更新失败: %s", e)


async def job_fetch_nav() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.fundamental import fetch_fundamental
        codes = await _codes()
        if not codes:
            return
        r = await fetch_fundamental(_http_client, codes)
        _ok("fetch_nav", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_nav", e)


async def job_fetch_kline() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.historical import fetch_historical
        codes = await _codes()
        if not codes:
            return
        r = await fetch_historical(_http_client, codes)
        _ok("fetch_kline", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_kline", e)


async def job_fetch_nav_qdii() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.fundamental import fetch_fundamental
        codes = await _qdii()
        if not codes:
            return
        r = await fetch_fundamental(_http_client, codes)
        _ok("fetch_nav_qdii", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_nav_qdii", e)


async def job_daily_save() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        mid = await publish_event("daily_save", {
            "date": datetime.now().strftime("%Y-%m-%d")
        })
        if mid:
            _ok("daily_save", (time.monotonic() - s) * 1000)
        else:
            raise ValueError("publish failed")
    except Exception as e:
        _fail("daily_save", e)


async def job_check_partitions() -> None:
    s = time.monotonic()
    try:
        from processors.saver import ensure_partition
        now = datetime.now()
        if now.month == 12:
            nm = now.replace(year=now.year + 1, month=1, day=1)
        else:
            nm = now.replace(month=now.month + 1, day=1)
        await ensure_partition(_sf(), nm)
        _ok("check_partitions", (time.monotonic() - s) * 1000)
    except Exception as e:
        _fail("check_partitions", e)

async def job_check_calendar() -> None:
    s = time.monotonic()
    try:
        ny = datetime.now().year + 1
        async with _sf() as session:
            result = await session.execute(text(
                "SELECT count(*) FROM trade_calendar "
                "WHERE EXTRACT(year FROM trade_date)=:ny AND is_trading=true"
            ), {"ny": ny})
            n = result.scalar()
        if n < 200 or n > 260:
            await alert(
                title=f"{ny} calendar missing",
                message=f"count={n}", level="P1",
                webhook_url=settings.ALERT_WEBHOOK_URL,
            )
        _ok("check_calendar", (time.monotonic() - s) * 1000)
    except Exception as e:
        _fail("check_calendar", e)

async def _codes() -> list[str]:
    try:
        async with _sf() as session:
            result = await session.execute(text(
                "SELECT code FROM fund_category WHERE category='LOF' ORDER BY code"
            ))
            return [r[0] for r in result.fetchall()]
    except Exception:
        return []


async def _qdii() -> list[str]:
    try:
        async with _sf() as session:
            result = await session.execute(text(
                "SELECT code FROM fund_info "
                "WHERE status='active' AND fund_type='QDII'"
            ))
            return [r[0] for r in result.fetchall()]
    except Exception:
        return []
