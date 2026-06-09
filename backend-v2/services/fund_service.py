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

    # 3. 查询数据
    # 如果有 amount_min 筛选，需要先获取所有数据，然后在 Python 层筛选
    # 因为 amount_min 筛选依赖实时数据（取今日实时成交额和昨日成交额的更大值）
    need_python_filter = amount_min is not None

    async with session_factory() as session:
        if need_python_filter:
            # 获取所有数据（不带分页）
            query = (
                f"SELECT * FROM fund_snapshot {where} "
                f"ORDER BY {sort_col} {sort_dir} NULLS LAST, code ASC"
            )
            result = await session.execute(text(query), params)
            all_rows = [dict(r._mapping) for r in result.fetchall()]
        else:
            # 查询总数
            count_row = await session.execute(
                text(f"SELECT COUNT(*) FROM fund_snapshot {where}"), params
            )
            total = count_row.scalar() or 0

            # 查询分页数据
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

    # 4. 合并实时数据
    if need_python_filter:
        # 先合并实时数据到所有数据
        if realtime_available and realtime_data:
            all_rows = _merge_realtime(all_rows, realtime_data)

        # 5.1 成交额筛选（取今日实时成交额和昨日成交额的更大值）
        filtered_rows = await _filter_by_amount(all_rows, amount_min, session_factory)

        # 更新总数
        total = len(filtered_rows)

        # 分页
        offset = (page - 1) * size
        rows = filtered_rows[offset:offset + size]
    else:
        # 合并实时数据到分页数据
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

    # 5.7 盘中注入估算净值
    from services.est_nav_service import get_est_nav_cache
    est_nav_map = await get_est_nav_cache()
    _normalize_frontend_fields(rows, est_nav_map)

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

    from services.est_nav_service import get_est_nav_cache
    est_nav_map = await get_est_nav_cache()
    _normalize_frontend_fields([fund_dict], est_nav_map)

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

    from services.est_nav_service import get_est_nav_cache
    est_nav_map = await get_est_nav_cache()
    _normalize_frontend_fields(rows, est_nav_map)

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
                   volume, amount, change_pct, float_share, turnover_rate
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
        vol = row.get("volume")
        tr = row.get("turnover_rate")
        cl = row.get("close")
        amt = row.get("amount")

        # 场内份额：从 volume/turnover_rate 计算
        shares = round(vol / tr, 2) if vol and tr and tr > 0 else row.get("float_share")

        # 成交额补算
        if (not amt or amt == 0) and vol and vol > 0 and cl and cl > 0:
            amt = round(vol * 100 * cl, 2)

        chart.append({
            "date": str(row["trade_date"]),
            "price": cl,
            "nav": row.get("nav"),
            "premium_rate": row.get("premium_rate"),
            "volume": vol,
            "amount": amt,
            "change_pct": row.get("change_pct"),
            "on_exchange_shares": shares,
            "turnover_rate": tr,
            "avg_premium_3d": row.get("avg_premium_3d"),
        })

    # 截取请求的天数
    chart = chart[-days:] if len(chart) > days else chart

    return chart


# ── 持仓查询 ────────────────────────────────────────────────


def _detect_holdings_type(name: str) -> str | None:
    """从基金名称判断无法展示股票持仓的类型，返回原因或 None"""
    if not name:
        return None
    n = name.upper()
    if "货币" in name:
        return "货币基金不展示股票持仓"
    if "债" in name and "QDII" not in n:
        return "债券基金主要持有债券资产，不展示股票持仓"
    if any(k in name for k in ("原油", "黄金", "白银", "贵金属", "大宗商品", "油气")):
        return "商品基金主要持有期货/海外资产，不展示股票持仓"
    if "FOF" in n or "基金中基金" in name:
        return "FOF基金主要持有其他基金份额，不展示股票持仓"
    return None


async def get_fund_holdings(session_factory, code: str) -> dict:
    """十大持仓 + 每只股票的实时涨跌幅"""
    code = code.zfill(6)

    async with session_factory() as session:
        row = await session.execute(
            text("SELECT * FROM fund_holdings WHERE code = :code"),
            {"code": code},
        )
        result = row.first()

    if not result:
        async with session_factory() as session:
            r = await session.execute(
                text("SELECT name FROM fund_info WHERE code = :code"),
                {"code": code},
            )
            name_row = r.first()
        fund_name = name_row[0] if name_row else ""
        reason = _detect_holdings_type(fund_name)
        return {
            "code": code,
            "name": fund_name,
            "holdings": [],
            "quarter": None,
            "no_holdings_reason": reason,
        }

    data = dict(result._mapping)

    # 补充每只持仓股票的实时涨跌幅
    holdings = data.get("holdings", [])
    if holdings:
        import httpx
        from fetchers.asset_quote import fetch_asset_quotes

        stock_codes = [h["code"] for h in holdings if h.get("code")]
        if stock_codes:
            # 从 asset_master 查真实 market
            async with session_factory() as qsession:
                r = await qsession.execute(text(
                    "SELECT code, market FROM asset_master WHERE code = ANY(:codes)"
                ), {"codes": stock_codes})
                market_map = {row[0]: row[1] for row in r.fetchall()}

            assets = []
            for c in stock_codes:
                m = market_map.get(c, "SZ")
                assets.append({"code": c, "market": m, "asset_type": "stock"})
            try:
                async with httpx.AsyncClient() as client:
                    quotes = await fetch_asset_quotes(client, assets)
                for h in holdings:
                    h["change_pct"] = quotes.get(h.get("code"))
                logger.info("[HOLDINGS] 涨跌幅获取成功: %d 条, data keys=%s", len(quotes), list(data.keys()))
            except Exception as e:
                logger.warning("[HOLDINGS] 涨跌幅获取失败: %s", e, exc_info=True)

    return data


# ── 内部辅助 ────────────────────────────────────────────────


async def _get_realtime_with_protection() -> tuple[Optional[dict], bool]:
    """
    读实时数据，带缓存击穿保护。
    返回 (data, available)。Redis 不可用时返回 (None, False)。
    """
    if not await is_redis_available():
        return None, False

    # 尝试读缓存（优先读当天的实时数据，使用北京时间）
    from datetime import timedelta
    beijing_now = datetime.now(timezone.utc) + timedelta(hours=8)
    today = beijing_now.strftime("%Y%m%d")
    data = await cache_get(f"rt:close:{today}")
    if not data:
        # 回退到 rt:all（兼容旧逻辑）
        data = await cache_get("rt:all")
    if data:
        return data, True

    # 缓存未命中，尝试获取锁
    lock_key = "lock:cache:rt:all"
    if await acquire_lock(lock_key, ttl=3):
        try:
            # 再次检查（可能其他请求已写入）
            data = await cache_get(f"rt:close:{today}")
            if not data:
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
            data = await cache_get(f"rt:close:{today}")
            if not data:
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


async def _filter_by_amount(rows: list[dict], amount_min: float, session_factory) -> list[dict]:
    """
    成交额筛选：取今日实时成交额和昨日成交额的更大值
    - 今日实时成交额：realtime_amount（来自Redis实时数据）
    - 昨日成交额：从fund_daily获取昨日数据
    """
    if not rows:
        return rows

    # 获取所有基金的昨日成交额
    codes = [r["code"] for r in rows if r.get("code")]
    if not codes:
        return rows

    # 从 fund_daily 获取昨日成交额
    from datetime import date, timedelta
    yesterday = date.today() - timedelta(days=1)

    async with session_factory() as session:
        result = await session.execute(text(
            "SELECT code, amount FROM fund_daily "
            "WHERE code = ANY(:codes) AND trade_date = :yesterday"
        ), {"codes": codes, "yesterday": yesterday})
        prev_amount_map = {r[0]: r[1] for r in result.fetchall()}

    filtered = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue

        # 今日实时成交额（如果有实时数据）
        realtime_amount = row.get("realtime_amount") or 0

        # 昨日成交额（从 fund_daily 获取）
        prev_amount = prev_amount_map.get(code) or 0

        # fund_snapshot.amount（来自 fund_daily 最新记录，可能是今日或昨日）
        snapshot_amount = row.get("amount") or 0

        # 取三者的更大值
        max_amount = max(realtime_amount, prev_amount, snapshot_amount)

        if max_amount >= amount_min:
            filtered.append(row)

    return filtered


def _merge_realtime(rows: list[dict], realtime: dict) -> list[dict]:
    """
    合并实时数据到基金列表。
    优先级：实时数据（Redis，每5分钟）> 快照数据（数据库，每天23:30）
    实时数据优先级最高，直接覆盖快照数据。
    """
    merged = []
    for row in rows:
        code = row.get("code")
        rt = realtime.get(code, {})
        if rt:
            # 实时价格（优先级最高）
            row["realtime_price"] = rt.get("realtime_price")
            row["realtime_nav"] = rt.get("realtime_nav")
            row["realtime_premium"] = rt.get("realtime_premium")

            # 以下字段：实时数据优先，直接覆盖
            if rt.get("change_pct") is not None:
                row["change_pct"] = rt["change_pct"]
            if rt.get("volume") is not None:
                row["volume"] = rt["volume"]
            # 注意：不覆盖 amount，保留 fund_snapshot.amount 作为昨日成交额
            # realtime_amount 单独存储，用于成交额筛选
            if rt.get("realtime_amount") is not None:
                row["realtime_amount"] = rt["realtime_amount"]
            if rt.get("turnover_rate") is not None:
                row["turnover_rate"] = rt["turnover_rate"]
            if rt.get("float_share") is not None:
                row["float_share"] = rt["float_share"]

            # 实时行情附加字段：直接覆盖
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


def _normalize_frontend_fields(rows: list[dict], est_nav_map: dict | None = None) -> None:
    """
    原地补齐前端需要的字段（v1 兼容）。
    - price: close 的别名
    - change_amount: 涨跌额 = change_pct / 100 * close
    - on_exchange_shares: float_share 的别名
    - can_purchase: purchase_status → bool/None
    - 盘中注入估算净值 (est_nav_map)
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

        # ── 盘中注入估算净值 (9:25-20:00，20:00后用正式净值) ──
        code = row.get("code")
        _now = datetime.now()
        _hm = _now.hour * 100 + _now.minute
        _in_trading = 925 <= _hm < 2000
        est = est_nav_map.get(code) if est_nav_map and code and _in_trading else None
        if est and est.get("est_nav") is not None:
            row["nav"] = est["est_nav"]
            row["is_formal_nav"] = False
            row["est_change_pct"] = est.get("est_change_pct")
            row["est_coverage"] = est.get("coverage")
        else:
            row["is_formal_nav"] = True

        # price: 优先用实时价 → close（前端 fund.price 引用）
        rt_price = row.get("realtime_price")
        if rt_price is not None:
            row["price"] = rt_price
        elif row.get("price") is None:
            row["price"] = row.get("close")
        # 实时溢价率重算：realtime_price + nav → premium_rate
        # 盘中有估算净值时，用 est_nav 重算（更准确）
        rt_price = row.get("realtime_price") or row.get("price")
        nav = row.get("nav")
        if est and est.get("est_nav") is not None and rt_price is not None:
            # 盘中：用估算净值算溢价
            if nav and nav > 0:
                row["premium_rate"] = round((rt_price - nav) / nav * 100, 2)
        else:
            rt_prem = row.get("realtime_premium")
            if rt_prem is not None:
                row["premium_rate"] = rt_prem
            elif rt_price is not None and nav and nav > 0:
                row["premium_rate"] = round((rt_price - nav) / nav * 100, 2)
        # 涨跌额（前端 fund.change_amount 引用）
        cp = row.get("change_pct")
        cl = row.get("close")
        if cp is not None and cl and cl > 0:
            row["change_amount"] = round(cp / 100 * cl, 4)
        # 场内份额（从 volume + turnover_rate 实时计算）
        vol = row.get("volume")
        tr = row.get("turnover_rate")
        if vol and tr and tr > 0:
            row["on_exchange_shares"] = round(vol / tr, 2)
        elif row.get("on_exchange_shares") is None:
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
    # 注意：amount_min 筛选移到 Python 层处理（需要实时数据，取今日实时成交额和昨日成交额的更大值）
    # amount_max 保持 SQL 层筛选
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
    elif filter_mode == "etf":
        conditions.append("category = 'ETF'")
    elif filter_mode == "lof":
        conditions.append("category = 'LOF'")

    return conditions, params
