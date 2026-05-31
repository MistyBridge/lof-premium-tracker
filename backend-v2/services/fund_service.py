"""
基金查询服务 — 列表/详情/批量/图表/持仓 + 实时合并 + 缓存击穿保护
"""
import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

from cache import acquire_lock, cache_get, cache_set, is_redis_available, release_lock
from constants import PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX
from exceptions import BadRequestException, NotFoundException
from trade_calendar import get_latest_trading_date, is_trading_day

logger = logging.getLogger("app")

# 排序白名单
SORT_WHITELIST = frozenset([
    "premium_rate", "close", "amount", "turnover_rate", "change_pct",
    "nav", "volume", "float_share", "aum", "code", "name",
])


# ── 基金列表 ────────────────────────────────────────────────


async def get_fund_list(
    session_factory,
    page: int = 1,
    size: int = PAGE_SIZE_DEFAULT,
    sort: str = "amount",
    order: str = "desc",
    search: Optional[str] = None,
    fund_type: Optional[str] = None,
    premium_min: Optional[float] = None,
    premium_max: Optional[float] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    turnover_min: Optional[float] = None,
    filter_mode: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict:
    """
    基金列表查询，合并实时数据 + 缓存击穿保护。
    返回 {"data": [...], "meta": {...}}
    """
    page = max(1, page)
    size = min(max(1, size), PAGE_SIZE_MAX)
    sort_col = sort if sort in SORT_WHITELIST else "amount"
    sort_dir = "DESC" if order.lower() == "desc" else "ASC"

    # 1. 读实时数据（带缓存击穿保护）
    realtime_data, realtime_available = await _get_realtime_with_protection()

    # 2. 构建查询
    conditions, params = _build_fund_conditions(
        search, fund_type, premium_min, premium_max,
        amount_min, amount_max, turnover_min,
        filter_mode, user_id, session_factory,
    )
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    # 3. 查询总数
    async with session_factory() as session:
        count_row = await session.execute(
            text(f"SELECT COUNT(*) FROM fund_snapshot {where}"), params
        )
        total = count_row.scalar() or 0

        # 4. 查询数据
        offset = (page - 1) * size
        query = (
            f"SELECT * FROM fund_snapshot {where} "
            f"ORDER BY {sort_col} {sort_dir} NULLS LAST, code ASC "
            f"LIMIT :limit OFFSET :offset"
        )
        params["limit"] = size
        params["offset"] = offset
        result = await session.execute(text(query), params)
        rows = [dict(r._mapping) for r in result.fetchall()]

    # 5. 合并实时数据
    if realtime_available and realtime_data:
        rows = _merge_realtime(rows, realtime_data)

    # 5.5 停牌标记（前端需要 is_suspended 布尔值）
    rows = _add_is_suspended(rows)

    # 5.6 合并三日均溢 + nav_date + aum + fetched_at + 字段对齐
    codes = [r["code"] for r in rows if r.get("code")]
    if codes:
        avg_map = await _batch_avg_premium_3d(session_factory, codes)
        nav_map = await _batch_nav_date(session_factory, codes)
        aum_map = await _batch_aum(session_factory, codes)
        fetched_map = await _batch_fetched_at(session_factory, codes)
        for row in rows:
            c = row.get("code")
            row["avg_premium_3d"] = avg_map.get(c)
            row["nav_date"] = nav_map.get(c)
            row["aum"] = aum_map.get(c)
            row["fetched_at"] = fetched_map.get(c)
    _normalize_frontend_fields(rows)

    # 6. 构建 meta
    is_trading = is_trading_day()
    meta = {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": (total + size - 1) // size if total > 0 else 0,
        "data_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_type": "realtime" if is_trading and realtime_available else "closing",
        "latest_trading_date": get_latest_trading_date().isoformat(),
        "realtime_available": realtime_available,
    }

    return {"data": rows, "meta": meta}


# ── 基金详情 ────────────────────────────────────────────────


async def get_fund_detail(session_factory, code: str) -> dict:
    """单基金详情，含费率 + 持仓"""
    code = code.zfill(6)
    import sys as _sys
    print(f"[DEBUG_DETAIL] called for {code}", file=_sys.stderr)

    async with session_factory() as session:
        # 基础数据
        row = await session.execute(
            text("SELECT * FROM fund_snapshot WHERE code = :code"),
            {"code": code},
        )
        fund = row.first()
        if not fund:
            raise NotFoundException(f"基金 {code} 不存在")
        fund_dict = dict(fund._mapping)

        # 费率
        fee_row = await session.execute(
            text("SELECT * FROM fund_fee WHERE code = :code"),
            {"code": code},
        )
        fee = fee_row.first()
        if fee:
            fund_dict.update(dict(fee._mapping))

        # 持仓
        hold_row = await session.execute(
            text("SELECT * FROM fund_holdings WHERE code = :code"),
            {"code": code},
        )
        holdings = hold_row.first()
        if holdings:
            fund_dict["holdings"] = holdings._mapping.get("holdings", [])
            fund_dict["holding_quarter"] = holdings._mapping.get("quarter")

    # 合并实时数据
    realtime_data, _ = await _get_realtime_with_protection()
    if realtime_data and code in realtime_data:
        fund_dict.update(realtime_data[code])

    # 停牌标记
    _add_is_suspended([fund_dict])

    # 三日均溢 + nav_date + aum + fetched_at + 字段对齐
    codes = [code]
    avg_map = await _batch_avg_premium_3d(session_factory, codes)
    fund_dict["avg_premium_3d"] = avg_map.get(code)
    nav_map = await _batch_nav_date(session_factory, codes)
    fund_dict["nav_date"] = nav_map.get(code)
    aum_map = await _batch_aum(session_factory, codes)
    fund_dict["aum"] = aum_map.get(code)
    fetched_map = await _batch_fetched_at(session_factory, codes)
    fund_dict["fetched_at"] = fetched_map.get(code)
    _normalize_frontend_fields([fund_dict])

    return fund_dict


# ── 批量查询 ────────────────────────────────────────────────


async def get_fund_batch(session_factory, codes: list[str]) -> list[dict]:
    """批量查询（最多 50 只）"""
    from constants import BATCH_CODES_MAX

    if len(codes) > BATCH_CODES_MAX:
        raise BadRequestException(f"批量查询上限 {BATCH_CODES_MAX} 只")

    codes = [c.zfill(6) for c in codes]

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM fund_snapshot WHERE code = ANY(:codes)"),
            {"codes": codes},
        )
        rows = [dict(r._mapping) for r in result.fetchall()]

    realtime_data, _ = await _get_realtime_with_protection()
    if realtime_data:
        rows = _merge_realtime(rows, realtime_data)

    rows = _add_is_suspended(rows)

    # 三日均溢 + nav_date + aum + fetched_at + 字段对齐
    avg_map = await _batch_avg_premium_3d(session_factory, codes)
    nav_map = await _batch_nav_date(session_factory, codes)
    aum_map = await _batch_aum(session_factory, codes)
    fetched_map = await _batch_fetched_at(session_factory, codes)
    for row in rows:
        c = row.get("code")
        row["avg_premium_3d"] = avg_map.get(c)
        row["nav_date"] = nav_map.get(c)
        row["aum"] = aum_map.get(c)
        row["fetched_at"] = fetched_map.get(c)
    _normalize_frontend_fields(rows)

    return rows


# ── 图表数据 ────────────────────────────────────────────────


async def get_fund_chart(
    session_factory,
    code: str,
    days: int = 30,
) -> dict:
    """
    基金日线图表数据。
    返回 {"chart": [...]}，字段名与前端对齐:
    date, price, nav, premium_rate, volume, amount, change_pct,
    on_exchange_shares, avg_premium_3d
    """
    code = code.zfill(6)
    days = min(max(1, days), 365)

    # 多取 2 天用于计算三日均溢首日值
    fetch_limit = days + 2

    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT trade_date, close, nav, premium_rate,
                   volume, amount, change_pct, float_share
            FROM fund_daily
            WHERE code = :code
            ORDER BY trade_date DESC
            LIMIT :limit
        """), {"code": code, "limit": fetch_limit})
        rows = [dict(r._mapping) for r in result.fetchall()]

    rows = list(reversed(rows))

    # 计算三日均溢（滚动 3 日算术平均）
    premium_history: list[float] = []
    for row in rows:
        pr = row.get("premium_rate")
        premium_history.append(pr if pr is not None else None)
        valid = [v for v in premium_history[-3:] if v is not None]
        row["avg_premium_3d"] = round(sum(valid) / len(valid), 4) if valid else None

    # 字段名对齐前端期望
    chart = []
    for row in rows:
        chart.append({
            "date": str(row["trade_date"]),
            "price": row.get("close"),
            "nav": row.get("nav"),
            "premium_rate": row.get("premium_rate"),
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "change_pct": row.get("change_pct"),
            "on_exchange_shares": row.get("float_share"),
            "avg_premium_3d": row.get("avg_premium_3d"),
        })

    # 截取请求的天数
    chart = chart[-days:] if len(chart) > days else chart

    return {"chart": chart}


# ── 持仓查询 ────────────────────────────────────────────────


async def get_fund_holdings(session_factory, code: str) -> dict:
    """十大持仓"""
    code = code.zfill(6)

    async with session_factory() as session:
        row = await session.execute(
            text("SELECT * FROM fund_holdings WHERE code = :code"),
            {"code": code},
        )
        result = row.first()

    if not result:
        raise NotFoundException(f"基金 {code} 无持仓数据")

    return dict(result._mapping)


# ── 内部辅助 ────────────────────────────────────────────────


async def _get_realtime_with_protection() -> tuple[Optional[dict], bool]:
    """
    读实时数据，带缓存击穿保护。
    返回 (data, available)。Redis 不可用时返回 (None, False)。
    """
    if not await is_redis_available():
        return None, False

    # 尝试读缓存
    data = await cache_get("rt:all")
    if data:
        return data, True

    # 缓存未命中，尝试获取锁
    lock_key = "lock:cache:rt:all"
    if await acquire_lock(lock_key, ttl=3):
        try:
            # 再次检查（可能其他请求已写入）
            data = await cache_get("rt:all")
            if data:
                return data, True
            # 缓存确实为空，返回 None（等待 fetcher 写入）
            return None, False
        finally:
            await release_lock(lock_key)
    else:
        # 没拿到锁，轮询等待
        for _ in range(40):  # 50ms * 40 = 2s
            await asyncio.sleep(0.05)
            data = await cache_get("rt:all")
            if data:
                return data, True
        return None, False


def _add_is_suspended(rows: list[dict]) -> list[dict]:
    """
    补充派生字段:
    - is_suspended: 停牌布尔值
    - premium_status: 溢价/折价/平价 状态文本
    """
    for row in rows:
        # 停牌标记
        if "is_suspended" in row and row["is_suspended"] is not None:
            row["is_suspended"] = bool(row["is_suspended"])
        else:
            row["is_suspended"] = row.get("suspension_status") == "suspended"

        # 溢价状态
        pr = row.get("premium_rate")
        if pr is not None:
            row["premium_status"] = "溢价" if pr > 0 else "折价" if pr < 0 else "平价"
        else:
            row["premium_status"] = None
    return rows


def _merge_realtime(rows: list[dict], realtime: dict) -> list[dict]:
    """合并实时数据到基金列表"""
    merged = []
    for row in rows:
        code = row.get("code")
        rt = realtime.get(code, {})
        if rt:
            row["realtime_price"] = rt.get("realtime_price")
            row["realtime_nav"] = rt.get("realtime_nav")
            row["realtime_premium"] = rt.get("realtime_premium")
            # 注意: 不能用 `or`，因为 0.0 是有效值（平盘/停牌）
            row["change_pct"] = rt.get("change_pct") if rt.get("change_pct") is not None else row.get("change_pct")
            row["volume"] = rt.get("volume") if rt.get("volume") is not None else row.get("volume")
            row["amount"] = rt.get("realtime_amount") if rt.get("realtime_amount") is not None else row.get("amount")
            row["turnover_rate"] = rt.get("turnover_rate") if rt.get("turnover_rate") is not None else row.get("turnover_rate")
            row["float_share"] = rt.get("float_share") if rt.get("float_share") is not None else row.get("float_share")
            # 实时行情附加字段（前端表头/卡片引用）
            for f in ("limit_up", "limit_down", "volume_ratio",
                       "float_market_cap", "total_market_cap",
                       "amplitude", "prev_close"):
                if rt.get(f) is not None:
                    row[f] = rt[f]
            # 停牌状态（实时判断优先）
            if "is_suspended" in rt:
                row["is_suspended"] = rt["is_suspended"]
        merged.append(row)
    return merged


async def _batch_nav_date(
    session_factory,
    codes: list[str],
) -> dict[str, Optional[str]]:
    """
    批量查询每只基金最新净值日期。
    返回 {code: nav_date_str}。
    """
    if not codes:
        return {}

    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT code, nav_date
            FROM fund_daily
            WHERE code = ANY(:codes)
              AND nav_date IS NOT NULL
            ORDER BY trade_date DESC
        """), {"codes": codes})
        rows = result.fetchall()

    seen: dict[str, str] = {}
    for row in rows:
        code = row[0]
        if code not in seen:
            seen[code] = str(row[1])
    return seen


async def _batch_aum(
    session_factory,
    codes: list[str],
) -> dict[str, Optional[float]]:
    """
    批量查询基金规模（亿元）。
    返回 {code: aum}。
    """
    if not codes:
        return {}

    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT code, aum FROM fund_info WHERE code = ANY(:codes)"
        ), {"codes": codes})
        rows = result.fetchall()

    return {row[0]: float(row[1]) if row[1] is not None else None for row in rows}


async def _batch_fetched_at(
    session_factory,
    codes: list[str],
) -> dict[str, Optional[str]]:
    """
    批量查询费率数据更新时间。
    返回 {code: fetched_at_str}。
    """
    if not codes:
        return {}

    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT code, fetched_at FROM fund_fee WHERE code = ANY(:codes)"
        ), {"codes": codes})
        rows = result.fetchall()

    return {
        row[0]: row[1].strftime("%Y-%m-%d %H:%M") if row[1] else None
        for row in rows
    }


def _normalize_frontend_fields(rows: list[dict]) -> None:
    """
    原地补齐前端需要的字段（v1 兼容）。
    - price: close 的别名
    - change_amount: 涨跌额 = change_pct / 100 * close
    - on_exchange_shares: float_share 的别名
    - can_purchase: purchase_status → bool/None
    """
    STATUS_TO_CAN = {
        "open": True,
        "restricted": True,
        "suspended": False,
    }
    for row in rows:
        # Decimal → float（PostgreSQL NUMERIC）
        for k, v in list(row.items()):
            if isinstance(v, Decimal):
                row[k] = float(v)
        # price 别名（前端 fund.price 引用）
        if row.get("price") is None:
            row["price"] = row.get("close")
        # 涨跌额（前端 fund.change_amount 引用）
        cp = row.get("change_pct")
        cl = row.get("close")
        if cp is not None and cl and cl > 0:
            row["change_amount"] = round(cp / 100 * cl, 4)
        # 场内份额别名（前端 fund.on_exchange_shares 引用）
        if row.get("on_exchange_shares") is None:
            row["on_exchange_shares"] = row.get("float_share")
        # can_purchase 布尔值
        if row.get("can_purchase") is None:
            ps = row.get("purchase_status")
            row["can_purchase"] = STATUS_TO_CAN.get(ps)
        # 成交额补算：amount=0 但 volume>0 时，用 volume*100*close 估算
        amt = row.get("amount")
        vol = row.get("volume")
        cl = row.get("close")
        if (amt is None or amt == 0) and vol and vol > 0 and cl and cl > 0:
            row["amount"] = round(vol * 100 * cl, 2)


async def _batch_avg_premium_3d(
    session_factory,
    codes: list[str],
) -> dict[str, Optional[float]]:
    """
    批量查询近 3 个交易日收盘溢价率的算术平均。
    返回 {code: avg_premium_3d}。
    """
    if not codes:
        return {}

    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT code, premium_rate
            FROM (
                SELECT code, premium_rate,
                       ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn
                FROM fund_daily
                WHERE code = ANY(:codes)
            ) sub
            WHERE rn <= 3
        """), {"codes": codes})
        rows = result.fetchall()

    # 聚合: 每个 code 取近 3 天的 premium_rate 算术平均
    from collections import defaultdict
    rates_map: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        code = row[0]
        rate = row[1]
        if rate is not None:
            rates_map[code].append(float(rate))

    return {
        code: round(sum(rates) / len(rates), 4) if rates else None
        for code, rates in rates_map.items()
    }


def _build_fund_conditions(
    search, fund_type, premium_min, premium_max,
    amount_min, amount_max, turnover_min,
    filter_mode, user_id, session_factory,
) -> tuple[list[str], dict]:
    """构建 WHERE 条件"""
    conditions = []
    params: dict[str, Any] = {}

    if search:
        conditions.append("(code LIKE :search OR name LIKE :search)")
        params["search"] = f"%{search}%"
    if fund_type:
        conditions.append("fund_type = :fund_type")
        params["fund_type"] = fund_type
    if premium_min is not None:
        conditions.append("premium_rate >= :premium_min")
        params["premium_min"] = premium_min
    if premium_max is not None:
        conditions.append("premium_rate <= :premium_max")
        params["premium_max"] = premium_max
    if amount_min is not None:
        conditions.append("amount >= :amount_min")
        params["amount_min"] = amount_min
    if amount_max is not None:
        conditions.append("amount <= :amount_max")
        params["amount_max"] = amount_max
    if turnover_min is not None:
        conditions.append("turnover_rate >= :turnover_min")
        params["turnover_min"] = turnover_min
    if filter_mode == "watchlist" and user_id:
        conditions.append(
            "code IN (SELECT fund_code FROM user_watchlist WHERE user_id = :wl_uid)"
        )
        params["wl_uid"] = user_id

    return conditions, params
