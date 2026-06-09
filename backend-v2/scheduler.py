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
from utils import beijing_now, beijing_today_str


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
    # 估算净值 — 交易时间内每5分钟
    scheduler.add_job(job_est_nav, IntervalTrigger(minutes=5), id="est_nav")
    # 估算净值快照 — 交易日 15:05 保存一次
    scheduler.add_job(job_save_est_nav, CronTrigger(hour=15, minute=5), id="save_est_nav",
                      name="保存估算净值", replace_existing=True, misfire_grace_time=300)
    # 日历重载 — 每10分钟检查一次（如果日历加载失败则重试）
    scheduler.add_job(job_reload_calendar, IntervalTrigger(minutes=10), id="reload_calendar")
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
        async with _sf()() as session:
            result = await session.execute(text(
                "SELECT count(*) FROM job_log "
                "WHERE job_name=:jid AND status='success' "
                "AND date(started_at)=current_date"
            ), {"jid": jid})
            return result.scalar() > 0
    except Exception:
        return False

def _ok(jid, ms, n=0):
    _failures[jid] = 0
    logger.info("[JOB] %s ok %.0fms %d", jid, ms, n)
    t = asyncio.create_task(_log(jid, "success", ms, n))
    t.add_done_callback(lambda _: None)  # prevent GC of task


def _fail(jid, e):
    _failures[jid] = _failures.get(jid, 0) + 1
    c = _failures[jid]
    logger.error("[JOB] %s fail #%d: %s", jid, c, e)
    t = asyncio.create_task(_log(jid, "failed", err=str(e)))
    t.add_done_callback(lambda _: None)  # prevent GC of task
    if c >= 3:
        asyncio.create_task(alert(title=jid+" failed", message=str(e), level="P1", webhook_url=settings.ALERT_WEBHOOK_URL))

async def _log(jid: str, st: str, ms: float = 0,
               n: int = 0, err: str = "") -> None:
    try:
        sf = _sf()
        if sf is None:
            logger.warning("[LOG] session_factory 为 None, 跳过写入: %s %s", jid, st)
            return
        async with sf() as session:
            await session.execute(text(
                "INSERT INTO job_log"
                "(job_name,status,duration_ms,detail,started_at,finished_at) "
                "VALUES(:jid,:st,:ms,:err,NOW(),NOW())"
            ), {"jid": jid, "st": st, "ms": int(ms), "err": err})
            await session.commit()
            logger.debug("[LOG] job_log 记录成功: %s %s", jid, st)
    except Exception as e:
        logger.warning("[LOG] job_log 写入失败: %s %s - %s", jid, st, e)

async def job_scan_codes() -> None:
    """扫描基金代码列表（使用本地 all_lof_codes.json）"""
    s = time.monotonic()
    try:
        import json
        from pathlib import Path
        codes_file = Path(__file__).parent / "all_lof_codes.json"
        if not codes_file.exists():
            raise ValueError("all_lof_codes.json 不存在")
        with open(codes_file, "r", encoding="utf-8") as f:
            codes_data = json.load(f)
        await publish_event("scan_codes", {
            "data": [{"code": x.get("code"), "name": x.get("name")} for x in codes_data]
        })
        _ok("scan_codes", (time.monotonic() - s) * 1000, len(codes_data))
    except Exception as e:
        _fail("scan_codes", e)


async def job_fetch_info() -> None:
    s = time.monotonic()
    try:
        from fetchers.info import fetch_info
        codes = await _codes()
        if not codes:
            logger.warning("[SCHEDULER] fetch_info 跳过: 无 LOF 代码")
            _fail("fetch_info", ValueError("无 LOF 代码，_codes() 返回空"))
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

    # 刷新物化视图（每5分钟同步数据到快照）
    try:
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(async_session_factory)
    except Exception as e:
        logger.warning("[SCHEDULER] 物化视图刷新失败: %s", e)


async def job_fetch_nav() -> None:
    if not is_trading_day():
        logger.info("[SCHEDULER] fetch_nav 跳过: 非交易日")
        return
    s = time.monotonic()
    try:
        from fetchers.fundamental import fetch_fundamental
        from cache import cache_set
        from datetime import date as _date
        from sqlalchemy import text as sql_text
        codes = await _codes()
        logger.info("[SCHEDULER] fetch_nav 开始: %d 只基金", len(codes))
        if not codes:
            logger.warning("[SCHEDULER] fetch_nav 跳过: 无 LOF/ETF 代码")
            _fail("fetch_nav", ValueError("无 LOF 代码"))
            return
        r = await fetch_fundamental(_http_client, codes)
        logger.info("[SCHEDULER] fetch_nav 获取 %d 条净值数据", len(r))

        if r:
            # 1. 写 Redis
            nav_map = {item["code"]: item for item in r if item.get("code")}
            await cache_set("nav:all", nav_map, ttl=86400)
            logger.info("[SCHEDULER] fetch_nav Redis 更新: %d 条", len(nav_map))

            # 2. 更新 DB (fund_daily)
            updated = 0
            sf = _sf()
            if sf:
                async with sf() as session:
                    for item in r:
                        code = item.get("code")
                        nav = item.get("nav")
                        nav_date = item.get("nav_date")
                        if not code or not nav or not nav_date:
                            continue
                        if isinstance(nav_date, str):
                            try:
                                nav_date = _date.fromisoformat(nav_date)
                            except (ValueError, TypeError):
                                continue
                        try:
                            result = await session.execute(sql_text(
                                "UPDATE fund_daily "
                                "SET nav = :nav, nav_date = :nav_date, nav_type = 'confirmed', nav_source = 'lsjz' "
                                "WHERE code = :code "
                                "AND trade_date = (SELECT MAX(trade_date) FROM fund_daily WHERE code = :code)"
                            ), {"code": code, "nav": float(nav), "nav_date": nav_date})
                            if result.rowcount > 0:
                                updated += 1
                        except Exception:
                            pass
                    await session.commit()

                    # 3. 刷新物化视图
                    try:
                        from processors.saver import refresh_materialized_view
                        await refresh_materialized_view(sf)
                    except Exception as e:
                        logger.warning("[SCHEDULER] 物化视图刷新失败: %s", e)

                logger.info("[SCHEDULER] fetch_nav DB 更新: %d 条", updated)

            # 4. 同时发布到 Stream（供其他消费者使用）
            await publish_event("nav", {"data": r})

        _ok("fetch_nav", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        logger.error("[SCHEDULER] fetch_nav 失败: %s", e)
        _fail("fetch_nav", e)


async def job_fetch_kline() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.historical import fetch_historical
        codes = await _codes()
        if not codes:
            logger.warning("[SCHEDULER] fetch_kline 跳过: 无 LOF 代码")
            _fail("fetch_kline", ValueError("无 LOF 代码"))
            return
        r = await fetch_historical(_http_client, codes)
        # 转换格式并发布到 Stream
        kdata = {item["code"]: item["klines"] for item in r if item.get("klines")}
        if kdata:
            await publish_event("kline", {"type": "fund", "data": kdata})
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
            logger.warning("[SCHEDULER] fetch_nav_qdii 跳过: 无 QDII 代码")
            _fail("fetch_nav_qdii", ValueError("无 QDII 代码"))
            return
        r = await fetch_fundamental(_http_client, codes)
        # 发布 NAV 数据到 Stream 供 consumer 处理
        if r:
            await publish_event("nav", {"data": r})
        _ok("fetch_nav_qdii", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_nav_qdii", e)


async def job_daily_save() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        mid = await publish_event("daily_save", {
            "date": beijing_today_str("%Y-%m-%d")
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
        async with _sf()() as session:
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


async def job_reload_calendar() -> None:
    """如果交易日历加载失败，定期重试"""
    from trade_calendar import is_calendar_loaded
    if is_calendar_loaded():
        return  # 已加载，跳过
    try:
        from trade_calendar import reload_calendar
        async with _sf()() as session:
            await reload_calendar(session)
            await session.commit()
    except Exception as e:
        logger.warning("[CALENDAR] 日历重载失败: %s", e)

async def _codes() -> list[str]:
    try:
        async with _sf()() as session:
            result = await session.execute(text(
                "SELECT code FROM fund_category WHERE category IN ('LOF', 'ETF') ORDER BY code"
            ))
            codes = [r[0] for r in result.fetchall()]
            if not codes:
                logger.warning("[SCHEDULER] _codes() 返回空列表，fund_category 可能无 LOF/ETF 数据")
            return codes
    except Exception as e:
        logger.warning("[SCHEDULER] _codes() 查询失败: %s", e)
        return []


async def _qdii() -> list[str]:
    try:
        async with _sf()() as session:
            result = await session.execute(text(
                "SELECT code FROM fund_info WHERE fund_type='QDII'"
            ))
            return [r[0] for r in result.fetchall()]
    except Exception as e:
        logger.warning("[SCHEDULER] _qdii() 查询失败: %s", e)
        return []


async def job_est_nav() -> None:
    """估算净值 — 交易日 9:25-20:00 运行，20:00后清理缓存切换正式净值"""
    now = beijing_now()
    hour_min = now.hour * 100 + now.minute

    # 20:00后清理缓存，切换正式净值
    if hour_min >= 2000:
        from cache import cache_delete
        await cache_delete("est_nav:v2")
        return

    # 9:25-20:00运行估算
    if not is_trading_day() or hour_min < 925:
        return

    s = time.monotonic()
    try:
        from services.est_nav_service import run_est_nav
        data = await run_est_nav(_http_client)
        _ok("est_nav", (time.monotonic() - s) * 1000, len(data))
    except Exception as e:
        _fail("est_nav", e)


async def job_save_est_nav() -> None:
    """交易日 15:05 保存估算净值快照（每日一次）"""
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from services.est_nav_service import save_est_nav_snapshot
        count = await save_est_nav_snapshot(_http_client)
        _ok("save_est_nav", (time.monotonic() - s) * 1000, count)
    except Exception as e:
        _fail("save_est_nav", e)
