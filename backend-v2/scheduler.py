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
    # 净值每 2 小时拉一次（原来只在每天 08:00 跑一次）。
    # 跨境/QDII 的净值要等海外市场收盘、基金公司估值后才披露，通常落在傍晚到
    # 深夜；每天只跑一次的话，最坏要等第二天早上才入库 —— 这段窗口里页面挂的是
    # 明明可以更新、却没更新的旧净值（#208 之后会如实标注净值日期，但数值本身
    # 仍然落后）。名单 2080 只，单次约 40 秒，12 次/天，对 lsjz 压力可忽略。
    scheduler.add_job(job_fetch_nav, CronTrigger(hour="*/2", minute=0), id="fetch_nav")
    scheduler.add_job(job_fetch_kline, CronTrigger(hour=20, minute=30), id="fetch_kline")
    # 原来还有一个 fetch_nav_qdii 单独再跑一遍 QDII。实测 28 只 QDII **全部**已经
    # 在采集名单内（名单外 0 只），等于把同一批请求发两遍 —— 已并入
    # _nav_codes() 的并集，不再单独调度。
    scheduler.add_job(job_daily_save, CronTrigger(hour=8, minute=30), id="daily_save",
                      name="日终入库", replace_existing=True, misfire_grace_time=1800)
    scheduler.add_job(job_check_partitions, CronTrigger(day=1, hour=9, minute=0), id="check_partitions")
    scheduler.add_job(job_check_calendar, CronTrigger(month=12, day=1, hour=9, minute=0), id="check_calendar")
    # 估算净值 — 交易时间内每5分钟
    scheduler.add_job(job_est_nav, IntervalTrigger(minutes=5), id="est_nav")
    # 估算净值快照 — 交易日 16:00 保存一次
    scheduler.add_job(job_save_est_nav, CronTrigger(hour=16, minute=0), id="save_est_nav",
                      name="保存估算净值", replace_existing=True, misfire_grace_time=300)
    # 日历重载 — 每10分钟检查一次（如果日历加载失败则重试）
    scheduler.add_job(job_reload_calendar, IntervalTrigger(minutes=10), id="reload_calendar")
    # 持仓刷新 — 每周六 8:00 全量刷新十大持仓（季度数据每周检一次足够）
    scheduler.add_job(job_fetch_holdings, CronTrigger(day_of_week="sat", hour=8, minute=0), id="fetch_holdings")
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
    """每周同步基金名单：从权威源补全 fund_category

    原实现只读本地 all_lof_codes.json 然后 publish_event，既不联网也不写库，
    导致 fund_category 自静态导入后再未更新 —— 新上市/转型的基金永远进不来。

    docs/plan/M7_调度层.md 原本就规定本任务应「用 push2 clist 扫描代码列表」，
    并预留 08:30 的时间窗好让 09:00 的 fetch_info 用上新名单，本实现即该设计意图。

    安全约定：只做新增，不自动删除疑似退市条目（--prune 需人工确认后执行 CLI）。
    """
    s = time.monotonic()
    try:
        from services.universe_service import collect_codes, sync_universe
        result = await sync_universe(apply=True, prune=False)
        _ok("scan_codes", (time.monotonic() - s) * 1000, result.inserted)

        # 广播最新采集名单（保留原有事件语义，便于前端/诊断消费）
        try:
            codes = await collect_codes()
            await publish_event("scan_codes", {
                "data": [{"code": c} for c in codes],
                "added": len(result.to_add),
            })
        except Exception as ev:  # noqa: BLE001 - 广播失败不影响同步结果
            logger.warning("[SCHEDULER] scan_codes 事件广播失败: %s", ev)
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


async def job_fetch_holdings() -> None:
    """每周六全量刷新十大持仓（季度数据，无进度追踪）"""
    s = time.monotonic()
    try:
        from fetchers.info import fetch_holdings_batch
        codes = await _codes()
        if not codes:
            logger.warning("[SCHEDULER] fetch_holdings 跳过: 无代码")
            _fail("fetch_holdings", ValueError("_codes() 返回空"))
            return
        r = await fetch_holdings_batch(_http_client, codes)
        _ok("fetch_holdings", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_holdings", e)


async def job_fetch_realtime() -> None:
    if not is_trading_day():
        return
    s = time.monotonic()
    try:
        from fetchers.realtime import fetch_realtime
        # 从数据库获取代码列表，传给 fetcher（避免依赖本地 JSON 文件路径）
        codes = await _codes()
        if not codes:
            logger.error("[SCHEDULER] fetch_realtime 跳过: _codes() 返回空，fund_category 表无 LOF/ETF 数据")
            _fail("fetch_realtime", ValueError("无 LOF/ETF 代码"))
            return
        r = await fetch_realtime(_http_client, codes=codes)
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

    # 净值归位（当日新增 close 行通常还没有 NAV）
    #
    # 顺序很重要：必须**先归位、再刷视图**。旧实现是先刷视图、再补 NAV，视图
    # 那一轮看到的还是"净值为空"的行，要等下一个 5 分钟周期才拿到净值；
    # 而且补 NAV 带着 `AND fd.nav IS NULL`，一旦补过一次（哪怕补的是滞后净值）
    # 就再也不会更新。跨境/QDII 净值滞后 1~2 个交易日，于是把两个交易日的
    # 行情混算成了溢价率（159509 虚高 32.07%，实际 27.93%）。
    # 完整背景见 processors/nav_sync.py 的模块说明。
    try:
        from database import async_session_factory
        from processors.nav_sync import sync_nav_to_latest_row
        async with async_session_factory() as session:
            await sync_nav_to_latest_row(session, codes)
            await session.commit()
    except Exception as e:
        logger.warning("[SCHEDULER] NAV归位失败: %s", e)

    # 刷新物化视图（每5分钟同步数据到快照）
    try:
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(async_session_factory)
    except Exception as e:
        logger.warning("[SCHEDULER] 物化视图刷新失败: %s", e)


async def job_fetch_nav() -> None:
    # 每 2 小时运行一次（2026-09-23 起；此前只在每天 08:00 跑一次）。
    # 跨境/QDII 净值在海外收盘后才披露，傍晚到深夜居多，加密频次可让它在
    # 公布后几小时内入库，而不是等第二天早上。
    s = time.monotonic()
    try:
        from fetchers.fundamental import fetch_fundamental
        from cache import cache_get, cache_set
        from constants import PARTIAL_DATA_THRESHOLD
        codes = await _nav_codes()
        logger.info("[SCHEDULER] fetch_nav 开始: %d 只基金", len(codes))
        if not codes:
            logger.warning("[SCHEDULER] fetch_nav 跳过: 无 LOF/ETF 代码")
            _fail("fetch_nav", ValueError("无 LOF 代码"))
            return
        r = await fetch_fundamental(_http_client, codes)
        logger.info("[SCHEDULER] fetch_nav 获取 %d 条净值数据", len(r))

        if r:
            # 1. 写 Redis（合并写入，见 processors/nav_sync.merge_nav_map）
            from processors.nav_sync import merge_nav_map, sync_nav_to_latest_row, upsert_nav_rows
            nav_map = {item["code"]: item for item in r if item.get("code")}
            prev = await cache_get("nav:all") or {}
            if prev and len(nav_map) < len(prev) * PARTIAL_DATA_THRESHOLD / 100:
                logger.warning(
                    "[SCHEDULER] fetch_nav 数据不完整: %d/%d（阈值 %d%%），"
                    "只并入本次拿到的条目，不覆盖既有缓存",
                    len(nav_map), len(prev), PARTIAL_DATA_THRESHOLD)
            merged = merge_nav_map(prev, nav_map)
            await cache_set("nav:all", merged, ttl=86400)
            logger.info("[SCHEDULER] fetch_nav Redis 更新: 本次 %d 条 → 缓存共 %d 条",
                        len(nav_map), len(merged))

            # 2. 更新 DB (fund_daily)
            updated = 0
            sf = _sf()
            if sf:
                async with sf() as session:
                    # 净值写入统一走 nav_sync.upsert_nav_rows：
                    # 除了把净值落到它自己的日期行，还会用该行的收盘价把
                    # premium_rate 一起对齐，避免同一行里 nav 与溢价率口径不一致。
                    updated = await upsert_nav_rows(session, r)

                    # 2.1 净值归位到最新交易日行（物化视图取最新交易日数据）
                    # 每次都重新归位并按新净值重算 premium_rate，不再"只补一次"。
                    # 详见 processors/nav_sync.py 的模块说明。
                    try:
                        await sync_nav_to_latest_row(session, codes)
                    except Exception as e:
                        logger.warning("[SCHEDULER] fetch_nav 净值归位失败: %s", e)

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
        logger.info("[SCHEDULER] fetch_kline 跳过: 非交易日")
        return
    s = time.monotonic()
    try:
        from fetchers.historical import fetch_historical, DAILY_KLINE_DAYS
        codes = await _codes()
        if not codes:
            logger.warning("[SCHEDULER] fetch_kline 跳过: 无 LOF 代码")
            _fail("fetch_kline", ValueError("无 LOF 代码"))
            return
        # 日终只取最近 10 天，减少不必要的网络请求
        r = await fetch_historical(_http_client, codes, days=DAILY_KLINE_DAYS)
        # fetch_historical 已内部 publish_event，此处只记录日志
        _ok("fetch_kline", (time.monotonic() - s) * 1000, len(r))
    except Exception as e:
        _fail("fetch_kline", e)


async def job_daily_save() -> None:
    # 每天 8:30 运行，保存昨日（交易日）数据
    from datetime import timedelta
    yesterday = beijing_now().date() - timedelta(days=1)
    if not is_trading_day(yesterday):
        return
    s = time.monotonic()
    try:
        mid = await publish_event("daily_save", {
            "date": yesterday.strftime("%Y-%m-%d")
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
        # 预建下月 + 本月分区（幂等，已存在则跳过）
        for offset in (1, 0):
            if now.month == 12:
                nm = now.replace(year=now.year + offset, month=1, day=1)
            else:
                nm = now.replace(month=now.month + offset, day=1)
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
        from services.universe_service import COLLECT_CATEGORIES
        async with _sf()() as session:
            result = await session.execute(
                text("SELECT code FROM fund_category WHERE category = ANY(:cats) "
                     "ORDER BY code"),
                {"cats": list(COLLECT_CATEGORIES)})
            codes = [r[0] for r in result.fetchall()]
            if not codes:
                logger.warning("[SCHEDULER] _codes() 返回空列表，"
                               "fund_category 可能无 %s 数据",
                               "/".join(COLLECT_CATEGORIES))
            return codes
    except Exception as e:
        logger.warning("[SCHEDULER] _codes() 查询失败: %s", e)
        return []


async def _nav_codes() -> list[str]:
    """净值采集的代码集合 = 采集名单 ∪ QDII。

    为什么要并集：`fetch_nav_qdii` 原本单独再跑一遍 QDII，但实测 28 只 QDII
    **全部**已经在采集名单里（名单外 0 只），等于同一批请求每天发两遍。
    用并集既保留"名单外的 QDII 也要拉"的兜底语义，又去掉这份重复。
    """
    codes = set(await _codes())
    codes.update(await _qdii())
    return sorted(codes)


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
    """估算净值 — 交易日 9:25-23:00 每5分钟计算（Redis 缓存 + SQL 入库）"""
    now = beijing_now()
    hour_min = now.hour * 100 + now.minute

    # 非交易时段跳过计算，保留已有缓存。
    # 末端从 20:00 延到 23:00：跨境/QDII 净值在傍晚到深夜才披露，而 est_nav 的
    # 基准净值取的是"最新已公布净值"（processors/est_nav.load_fund_meta）。净值在
    # 20:00 之后到货时，若估算已经停止刷新，就会出现「净值列是 T-1、估算列却按
    # T-2 算」的错位 —— 两列不同基准，用户没法横向比较。
    if not is_trading_day() or hour_min < 925 or hour_min >= 2300:
        return

    s = time.monotonic()
    try:
        from services.est_nav_service import run_est_nav, save_est_nav_slice
        data = await run_est_nav(_http_client)
        if data:
            # 5分钟切片写入 SQL（异步，失败不影响主流程）
            try:
                await save_est_nav_slice(data)
            except Exception as e:
                logger.warning("[EST_NAV] 切片入库失败: %s", e)
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
