"""
pipeline — Stream 消费者主循环 + 事件分派 + daily_save 编排
在 app.py lifespan 中作为 asyncio.create_task 启动。
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from cache import cache_get, cache_set, safe_set_realtime
from metrics import metrics
from mq import ack_event, consume_events
from processors.calculator import calc_daily_fields
from processors.suspension import judge_suspension
from processors.normalize import (
    clean_code,
    normalize_info,
    normalize_kline,
    normalize_nav,
    normalize_realtime,
)
from processors.saver import (
    batch_upsert,
    refresh_materialized_view,
    save_daily_batch,
    save_fee_batch,
    save_holdings_batch,
    save_info_batch,
    save_job_log,
    save_kline_batch,
)
from processors.validator import (
    deduplicate,
    mark_limit_status,
    validate_info,
    validate_kline,
    validate_nav,
    validate_realtime,
)

logger = logging.getLogger("consumer")

# 毒消息计数器
_poison_counter: dict[str, int] = {}
MAX_RETRY = 3


# ── 消费者主循环 ────────────────────────────────────────────


async def stream_consumer(session_factory) -> None:
    """
    后台消费者：从 Redis Stream 读取事件 → 处理 → ack。
    每个事件独立处理，单个失败不影响其他事件。
    """
    logger.info("Stream 消费者启动")

    while True:
        try:
            events = await consume_events(count=10, block_ms=2000)
            for event in events:
                try:
                    await dispatch(event, session_factory)
                    await ack_event(event["id"])
                except Exception as e:
                    logger.error(
                        "事件处理失败: type=%s id=%s error=%s",
                        event.get("type"), event["id"], e,
                    )
                    await _handle_poison_message(event, e)

        except asyncio.CancelledError:
            logger.info("Stream 消费者停止")
            break
        except Exception as e:
            logger.error("消费者异常: %s", e)
            await asyncio.sleep(5)


# ── 事件分派 ────────────────────────────────────────────────


async def dispatch(event: dict, session_factory) -> None:
    """按事件类型分派到对应处理函数"""
    event_type = event["type"]
    data = event["data"]
    batch_id = str(uuid.uuid4())

    handlers = {
        "realtime": process_realtime,
        "nav": process_nav,
        "kline": process_kline,
        "info": process_info,
        "daily_save": process_daily_save,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(data, batch_id, session_factory)
    else:
        logger.warning("未知事件类型: %s", event_type)


# ── 各事件处理函数 ──────────────────────────────────────────


async def process_realtime(data: dict, batch_id: str, session_factory) -> None:
    """实时行情: normalize → validate → 停牌判断 → 写 Redis"""
    records = data.get("data", [])
    source = data.get("fetch_source", "push2")

    normalized = [normalize_realtime(r, source=source) for r in records]
    validated = [validate_realtime(r) for r in normalized]
    deduped = deduplicate(validated, key="code")
    marked = [mark_limit_status(r) for r in deduped]

    # ── 停牌判断（每5分钟快照时同步更新）──
    prev_suspend = await cache_get("suspension:all") or {}
    suspension_map = {}
    for r in marked:
        code = r.get("code")
        if not code:
            continue
        status = judge_suspension(
            volume=r.get("volume"),
            close=r.get("realtime_price"),
            prev_volume=prev_suspend.get(code, {}).get("prev_volume"),
        )
        r["suspension_status"] = status
        suspension_map[code] = {
            "status": status,
            "prev_volume": r.get("volume"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    await cache_set("suspension:all", suspension_map, ttl=600)

    realtime_map = {r["code"]: r for r in marked if r.get("code")}
    await safe_set_realtime(realtime_map)

    _beijing = datetime.now(timezone.utc) + timedelta(hours=8)
    today = _beijing.strftime("%Y%m%d")
    await cache_set(f"rt:close:{today}", realtime_map, ttl=86400)

    suspended_count = sum(1 for v in suspension_map.values() if v["status"] == "suspended")
    metrics.record_fetch("realtime", success=True, duration_ms=0)
    logger.info("实时行情处理完成: %d 条, 停牌 %d 只", len(realtime_map), suspended_count)


async def process_nav(data: dict, batch_id: str, session_factory) -> None:
    """净值: normalize → validate → 写 Redis + 更新 DB"""
    records = data.get("data", [])

    normalized = [normalize_nav(r) for r in records]
    validated = [r for r in (validate_nav(r) for r in normalized) if r is not None]

    nav_map = {r["code"]: r for r in validated if r.get("code")}
    await cache_set("nav:all", nav_map, ttl=86400)  # 24小时，确保daily_save能读到

    # 同步更新 fund_daily 表的 NAV 数据
    from datetime import date as _date
    updated = 0
    async with session_factory() as session:
        for item in validated:
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
                result = await session.execute(text(
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

    # 刷新物化视图
    try:
        from processors.saver import refresh_materialized_view
        await refresh_materialized_view(session_factory)
    except Exception as e:
        logger.warning("[NAV] 物化视图刷新失败: %s", e)

    metrics.record_fetch("nav", success=True, duration_ms=0)
    logger.info("净值处理完成: %d 条，DB更新: %d 条", len(nav_map), updated)


async def process_kline(data: dict, batch_id: str, session_factory) -> None:
    """日线: normalize → validate → 写 Redis + DB"""
    ktype = data.get("type", "fund")
    kdata = data.get("data", {})
    _beijing = datetime.now(timezone.utc) + timedelta(hours=8)
    today = _beijing.strftime("%Y%m%d")

    from processors.saver import save_kline_batch
    total_saved = 0

    for code, records in kdata.items():
        normalized = [normalize_kline(r, source="push2his") for r in records]
        validated = [r for r in (validate_kline(r) for r in normalized) if r is not None]
        if validated:
            # 写 Redis 缓存
            await cache_set(f"kline:{ktype}:{today}:{code}", validated, ttl=86400)
            # 写 DB（更新成交额等字段）
            saved = await save_kline_batch(session_factory, code, validated)
            total_saved += saved

    metrics.record_fetch("kline", success=True, duration_ms=0)
    logger.info("日线处理完成: %d 个代码, %d 条已保存到DB", len(kdata), total_saved)


async def process_info(data: dict, batch_id: str, session_factory) -> None:
    """持仓+基础信息: normalize → validate → 写 DB + Redis"""
    records = data.get("data", [])
    normalized = [normalize_info(r) for r in records]
    validated = [r for r in normalized if r.get("code")]

    info_records = [_extract_info(r) for r in validated]
    fee_records = [_extract_fee(r) for r in validated]
    holdings_records = [h for h in (_extract_holdings(r) for r in validated) if h is not None]
    category_records = [
        {"code": r.get("code"), "category": r.get("fund_type", "OTHER")}
        for r in info_records if r.get("fund_type")
    ]

    await save_info_batch(session_factory, info_records)
    await save_fee_batch(session_factory, fee_records)
    if holdings_records:
        await save_holdings_batch(session_factory, holdings_records)
    if category_records:
        from models import FundCategory
        await batch_upsert(session_factory, FundCategory, category_records, ["code", "category"])

    for r in validated:
        code = r.get("code")
        await cache_set(f"info:{code}", _extract_info(r), ttl=86400)
        await cache_set(f"fee:{code}", _extract_fee(r), ttl=3600)

    metrics.record_fetch("info", success=True, duration_ms=0)
    logger.info("基础信息处理完成: %d 条", len(validated))


async def process_daily_save(data: dict, batch_id: str, session_factory) -> None:
    """
    日终入库: 合并 Redis 收盘价+净值 → calculator → saver → 刷新物化视图。
    缺失字段自动沿用最近历史数据作为替补。
    """
    _beijing = datetime.now(timezone.utc) + timedelta(hours=8)
    today = _beijing.strftime("%Y%m%d")
    today_date = _beijing.date()

    # 1. 从 Redis 读取
    closing_data = await cache_get(f"rt:close:{today}") or {}
    nav_data = await cache_get("nav:all") or {}
    suspension_data = await cache_get("suspension:all") or {}

    # 2. 从 DB 读取基金列表 + 申购限额 + 最近历史数据（替补用）
    from sqlalchemy import text as sql_text
    async with session_factory() as session:
        rows = await session.execute(sql_text("SELECT code, name FROM fund_code_list"))
        code_list = [dict(r._mapping) for r in rows.fetchall()]
        # 读取申购限额
        fee_rows = await session.execute(sql_text(
            "SELECT code, purchase_limit FROM fund_fee"
        ))
        limit_map = {r[0]: r[1] for r in fee_rows.fetchall() if r[1] is not None}
        # 读取每只基金最近一条有净值的记录（替补用）
        fallback_rows = await session.execute(sql_text("""
            WITH ranked AS (
                SELECT code, nav, nav_date, close, open, high, low,
                       volume, amount, float_share, turnover_rate,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) as rn
                FROM fund_daily
                WHERE nav IS NOT NULL
            )
            SELECT code, nav, nav_date, close, open, high, low,
                   volume, amount, float_share, turnover_rate
            FROM ranked WHERE rn = 1
        """))
        fallback_map = {r[0]: dict(r._mapping) for r in fallback_rows.fetchall()}

    # 3. 合并数据（缺失字段从历史替补）
    merged = []
    for fund in code_list:
        code = fund["code"]
        closing = closing_data.get(code, {})
        nav = nav_data.get(code, {})
        fallback = fallback_map.get(code, {})

        if not closing:
            continue

        # 停牌状态（来自实时快照的判断结果）
        susp = suspension_data.get(code, {})
        susp_status = susp.get("status", closing.get("suspension_status", "unknown"))

        # 净值：优先用当天获取的，没有则用最近历史
        nav_val = nav.get("nav") or fallback.get("nav")
        nav_date_val = nav.get("nav_date") or fallback.get("nav_date")
        # nav_date 统一转 date 对象（Redis 里是字符串，DB 里是 date）
        if isinstance(nav_date_val, str):
            try:
                from datetime import date as _date
                nav_date_val = _date.fromisoformat(nav_date_val)
            except (ValueError, TypeError):
                nav_date_val = None
        nav_source = "lsjz" if nav.get("nav") else "fallback"

        record = {
            "code": code,
            "trade_date": today_date,
            "close": closing.get("realtime_price") or fallback.get("close"),
            "open": closing.get("open") or fallback.get("open"),
            "high": closing.get("high") or fallback.get("high"),
            "low": closing.get("low") or fallback.get("low"),
            "volume": closing.get("volume") or fallback.get("volume"),
            "amount": closing.get("realtime_amount") or fallback.get("amount"),
            "float_share": closing.get("float_share") or fallback.get("float_share"),
            "turnover_rate": closing.get("turnover_rate") or fallback.get("turnover_rate"),
            "nav": nav_val,
            "nav_date": nav_date_val,
            "nav_type": "confirmed",
            "nav_source": nav_source,
            "fetch_source": closing.get("fetch_source", "tencent"),
            "suspension_status": susp_status,
            "purchase_limit": limit_map.get(code),
            "fetch_batch_id": batch_id,
        }
        merged.append(record)

    # 4. 计算派生字段
    calculated = []
    for fund in merged:
        result = await calc_daily_fields(fund, prev_day=None, recent_3d=[])
        calculated.append(result)

    # 5. 写 DB
    save_result = await save_daily_batch(session_factory, calculated)

    # 6. 完整性校验
    expected = len(code_list)
    actual = save_result["success"]
    if expected > 0 and actual < expected * 0.95:
        logger.warning("daily_save 数据缺失: %d/%d", actual, expected)

    # 7. 刷新物化视图
    if not save_result["failed_batches"]:
        await refresh_materialized_view(session_factory)

    # 8. 记录日志
    await save_job_log(session_factory, "daily_save", save_result, batch_id)
    logger.info("daily_save 完成: %d/%d 条", actual, expected)


# ── 辅助函数 ────────────────────────────────────────────────


def _extract_info(record: dict) -> dict:
    """从统一 info 记录提取 fund_info 字段，从名称推断 fund_type"""
    fund_type = record.get("fund_type") or "OTHER"
    name = record.get("name") or ""

    # fundf10 返回投资风格（如"混合型-偏股"），不是交易类型
    # 从基金全称中推断 LOF/ETF/QDII
    if fund_type not in ("LOF", "ETF", "QDII"):
        name_upper = name.upper()
        if "QDII" in name_upper:
            fund_type = "QDII"
        elif "ETF" in name_upper:
            fund_type = "ETF"
        elif "LOF" in name_upper:
            fund_type = "LOF"

    code = record.get("code", "")
    # market 推断: 深市 15/16/17/18/19 开头, 沪市 50/51/52 开头
    market = "SZ" if code[:2] in ("15", "16", "17", "18", "19") else "SH"

    return {
        "code": code,
        "name": name,
        "fund_type": fund_type,
        "index_code": record.get("index_code"),
        "market": market,
        "aum": record.get("aum"),
        "listing_date": record.get("listing_date"),
        "redeem_days": record.get("redeem_days"),
        "qdii_quota_status": record.get("qdii_quota_status", "open"),
    }


def _extract_fee(record: dict) -> dict:
    """从统一 info 记录提取 fund_fee 字段"""
    return {
        "code": record.get("code"),
        "purchase_fee_rate": record.get("purchase_fee_rate"),
        "redemption_fee_rate": record.get("redemption_fee_rate"),
        "purchase_limit": record.get("purchase_limit"),
        "purchase_status": record.get("purchase_status"),
        "redeem_status": record.get("redeem_status"),
    }


def _extract_holdings(record: dict) -> dict | None:
    """从统一 info 记录提取 fund_holdings 字段"""
    holdings = record.get("holdings")
    if not holdings:
        return None
    return {
        "code": record.get("code"),
        "quarter": record.get("holding_quarter"),
        "holdings": holdings,  # JSONB 列直接接受 Python list
    }


async def _handle_poison_message(event: dict, error: Exception) -> None:
    """防止毒消息阻塞消费者"""
    event_id = event["id"]
    _poison_counter[event_id] = _poison_counter.get(event_id, 0) + 1

    if _poison_counter[event_id] >= MAX_RETRY:
        logger.error("毒消息丢弃: id=%s type=%s 失败 %d 次", event_id, event["type"], MAX_RETRY)
        await ack_event(event_id)
        del _poison_counter[event_id]


# ── 直接入口（不经过 Stream，用于测试和手动触发） ───────────


async def save_info_direct(records: list[dict], session_factory) -> dict:
    """
    直接将 fetcher 原始数据写入 DB（绕过 Redis Stream）。
    用于测试、手动触发、首次数据导入。

    records: fetch_info() 返回的原始数据列表
    """
    import uuid as _uuid
    batch_id = str(_uuid.uuid4())

    normalized = [normalize_info(r) for r in records]
    validated = [r for r in normalized if r.get("code")]

    info_records = [_extract_info(r) for r in validated]
    fee_records = [_extract_fee(r) for r in validated]
    holdings_records = [h for h in (_extract_holdings(r) for r in validated) if h is not None]
    category_records = [
        {"code": r.get("code"), "category": r.get("fund_type", "OTHER")}
        for r in info_records if r.get("fund_type")
    ]

    result = {}
    result["info"] = await save_info_batch(session_factory, info_records)
    result["fee"] = await save_fee_batch(session_factory, fee_records)
    if holdings_records:
        result["holdings"] = await save_holdings_batch(session_factory, holdings_records)
    if category_records:
        from models import FundCategory
        result["category"] = await batch_upsert(
            session_factory, FundCategory, category_records, ["code", "category"]
        )

    await save_job_log(session_factory, "info_direct", result.get("info", {}), batch_id)
    logger.info("直接入库完成: info=%s fee=%s",
                result.get("info", {}).get("success"),
                result.get("fee", {}).get("success"))
    return result
