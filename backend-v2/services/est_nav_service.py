"""
估算净值服务 — 独立模块，不依赖其他服务 (v2: 含持仓明细)

职责:
  1. 拉取资产涨跌幅 (asset_quote)
  2. 计算估算净值 (est_nav)
  3. 缓存结果到 Redis

Redis Key:
  est_nav:all  → 全部基金估算净值 (TTL 300s)
"""
import logging
import time

import httpx

import database
from cache import cache_get, cache_set
from fetchers.asset_quote import fetch_asset_quotes
from processors.est_nav import calc_all_est_navs, load_fund_meta, load_holdings
from metrics import metrics

logger = logging.getLogger("app")

# Redis Key (v2 = 包含 holding_details/index_detail/nav 完整字段)
EST_NAV_KEY = "est_nav:v2"
EST_NAV_TTL = 36000  # 10小时 — 保留到次日开盘，收盘后仍可查看


async def run_est_nav(client: httpx.AsyncClient) -> dict:
    """
    执行一次估算净值计算。

    Args:
        client: httpx.AsyncClient (复用调度器的连接)

    Returns:
        {fund_code: {est_nav, est_change_pct, ...}} 或空字典
    """
    start = time.monotonic()

    sf = database.async_session_factory
    if not sf:
        logger.warning("[EST_NAV_SERVICE] 数据库未初始化")
        return {}

    try:
        async with sf() as session:
            # 1. 加载元数据
            meta = await load_fund_meta(session)
            holdings = await load_holdings(session)
            both = set(meta.keys()) & set(holdings.keys())

            if not both:
                logger.warning("[EST_NAV_SERVICE] 无可计算的基金")
                return {}

            # 2. 收集需要查询的资产
            from sqlalchemy import text as sql_text
            r = await session.execute(sql_text(
                'SELECT code, market, asset_type FROM asset_master'
            ))
            asset_info = {
                row[0]: {'code': row[0], 'market': row[1], 'asset_type': row[2]}
                for row in r.fetchall()
            }

            need_quotes = set()
            for fc in both:
                for h in holdings[fc]:
                    need_quotes.add(h['asset_code'])
                m = meta[fc]
                if m['index_tcode']:
                    need_quotes.add(m['index_tcode'])

            quote_assets = []
            for acode in need_quotes:
                if acode in asset_info:
                    quote_assets.append(asset_info[acode])
                elif acode.startswith(('sh', 'sz', 'hk')):
                    quote_assets.append({'code': acode, 'market': '', 'asset_type': 'index'})

            # 3. 拉涨跌幅
            quotes = await fetch_asset_quotes(client, quote_assets)

            # 4. 计算估算净值
            results = await calc_all_est_navs(session, quotes)

        # 5. 序列化结果
        data = {}
        for fc, r in results.items():
            data[fc] = {
                'est_nav': r.est_nav,
                'est_change_pct': r.est_change_pct,
                'holdings_contrib': r.holdings_contrib,
                'index_contrib': r.index_contrib,
                'coverage': r.coverage,
                'holding_details': r.holding_details or [],
                'index_detail': r.index_detail,
                'nav': r.nav,
            }

        # 6. 写入 Redis
        await cache_set(EST_NAV_KEY, data, EST_NAV_TTL)

        elapsed = (time.monotonic() - start) * 1000
        ok = len(data) > 0
        metrics.record_fetch("est_nav", ok, elapsed)

        logger.info(
            "[EST_NAV_SERVICE] 完成: %d 只基金, %d 个涨跌幅, %.0fms",
            len(data), len(quotes), elapsed,
        )
        return data

    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        metrics.record_fetch("est_nav", False, elapsed)
        logger.error("[EST_NAV_SERVICE] 失败: %s", e, exc_info=True)
        return {}


async def get_est_nav_cache() -> dict:
    """从 Redis 读取估算净值缓存"""
    return await cache_get(EST_NAV_KEY) or {}


async def save_est_nav_snapshot(client: httpx.AsyncClient) -> int:
    """
    收盘后保存估算净值快照到数据库。
    复用 run_est_nav 的计算逻辑，将结果写入 fund_est_nav 表。
    返回保存的记录数。
    """
    from processors.saver import save_est_nav_batch
    from utils import beijing_today_date

    data = await run_est_nav(client)
    if not data:
        logger.warning("[EST_NAV_SNAPSHOT] 无数据可保存")
        return 0

    trade_date = beijing_today_date()
    records = []
    for fc, info in data.items():
        records.append({
            'code': fc,
            'est_nav': info.get('est_nav'),
            'est_change_pct': info.get('est_change_pct'),
            'holdings_contrib': info.get('holdings_contrib'),
            'index_contrib': info.get('index_contrib'),
            'coverage': info.get('coverage'),
            'nav': info.get('nav'),
        })

    sf = database.async_session_factory
    result = await save_est_nav_batch(sf, records, trade_date)
    saved = result.get('success', 0)
    logger.info("[EST_NAV_SNAPSHOT] 保存完成: %d 条, trade_date=%s", saved, trade_date)
    return saved


async def calc_single_est_nav(sf, code: str) -> dict | None:
    """
    按需计算单只基金的估算净值（缓存未命中时的降级方案）。
    返回与缓存格式相同的 dict，或 None。
    """
    from processors.est_nav import calc_est_nav, load_fund_meta, load_holdings
    from index_mapping import get_index_quote_code
    from sqlalchemy import text as sql_text
    import httpx

    fund_code = code.zfill(6)
    try:
        async with sf() as session:
            # 1. 获取该基金的净值和跟踪指数
            r = await session.execute(sql_text('''
                SELECT fd.nav, fi.index_code
                FROM fund_daily fd
                JOIN fund_info fi ON fi.code = fd.code
                WHERE fd.code = :code AND fd.nav IS NOT NULL
                AND fd.nav_date = (
                    SELECT MAX(nav_date) FROM fund_daily WHERE code = fd.code
                )
            '''), {'code': fund_code})
            row = r.fetchone()
            if not row or not row[0]:
                return None
            nav = float(row[0])
            idx_name = row[1]
            idx_tcode = get_index_quote_code(idx_name) if idx_name else None

            # 2. 获取持仓
            r2 = await session.execute(sql_text(
                'SELECT asset_code, weight FROM fund_asset_map WHERE fund_code = :code AND weight > 0'
            ), {'code': fund_code})
            holdings = [{'asset_code': ac, 'weight': float(wt)} for ac, wt in r2.fetchall()]
            if not holdings:
                return None

            # 3. 获取资产信息
            need_quotes = {h['asset_code'] for h in holdings}
            if idx_tcode:
                need_quotes.add(idx_tcode)

            r3 = await session.execute(sql_text(
                'SELECT code, market, asset_type FROM asset_master WHERE code = ANY(:codes)'
            ), {'codes': list(need_quotes)})
            asset_info = {row[0]: {'code': row[0], 'market': row[1], 'asset_type': row[2]} for row in r3.fetchall()}

            quote_assets = []
            for acode in need_quotes:
                if acode in asset_info:
                    quote_assets.append(asset_info[acode])
                elif acode.startswith(('sh', 'sz', 'hk')):
                    quote_assets.append({'code': acode, 'market': '', 'asset_type': 'index'})

        # 4. 拉涨跌幅
        async with httpx.AsyncClient(timeout=10) as client:
            quotes = await fetch_asset_quotes(client, quote_assets)

        # 5. 计算
        result = calc_est_nav(nav=nav, holdings=holdings, quotes=quotes, index_tcode=idx_tcode)

        return {
            'est_nav': result.est_nav,
            'est_change_pct': result.est_change_pct,
            'holdings_contrib': result.holdings_contrib,
            'index_contrib': result.index_contrib,
            'coverage': result.coverage,
            'holding_details': result.holding_details or [],
            'index_detail': result.index_detail,
            'nav': result.nav,
        }
    except Exception as e:
        logger.error("[EST_NAV_SERVICE] 单基金计算失败 %s: %s", code, e, exc_info=True)
        return None
