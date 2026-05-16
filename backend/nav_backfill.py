# -*- coding: utf-8 -*-
"""
NAV 净值回填任务 — 补充 daily_kline 中缺失的场外净值数据

用法：通过 /api/tasks API 触发，或直接调用 run_nav_backfill()
"""
import logging
import time
import threading
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from history_db import get_history_db

logger = logging.getLogger(__name__)

BATCH = 100
DELAY = 0.3          # 每个基金间隔，避免限流
MAX_WORKERS = 4
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://fund.eastmoney.com/",
}


def _make_session():
    s = requests.Session()
    s.trust_env = False
    r = Retry(total=1, backoff_factor=0.5, status_forcelist={502, 503, 504, 429})
    a = HTTPAdapter(max_retries=r, pool_connections=8, pool_maxsize=20)
    s.mount("http://", a)
    s.mount("https://", a)
    return s


def _fetch_nav_history(code, start_date, end_date):
    """从 lsjz API 拉取单只基金的历史净值"""
    url = (
        f"https://api.fund.eastmoney.com/f10/lsjz"
        f"?fundCode={code}&pageIndex=1&pageSize=400"
        f"&startDate={start_date}&endDate={end_date}"
    )
    s = _make_session()
    try:
        resp = s.get(url, headers=HEADERS, timeout=15)
        data = resp.json()
        ls = (data.get("Data") or {}).get("LSJZList") or []
        result = {}
        for item in ls:
            dt = item.get("FSRQ")
            nv = float(item.get("DWJZ") or 0)
            if dt and nv > 0:
                result[dt] = nv
        return result
    except Exception as e:
        logger.debug("NAV fetch failed for %s: %s", code, e)
        return {}


def run_nav_backfill(progress_callback=None):
    """
    回填 daily_kline 中缺失的 NAV 数据。
    串行处理，每个基金间隔 DELAY 避免限流。
    """
    hdb = get_history_db()
    conn = hdb._pool.getconn()
    try:
        # 1. 找到需要回填的基金及其日期范围
        with conn.cursor() as cur:
            cur.execute("""
                SELECT code, MIN(date)::TEXT AS beg, MAX(date)::TEXT AS ed,
                       COUNT(*) FILTER (WHERE nav IS NULL OR nav <= 0) AS missing
                FROM daily_kline
                GROUP BY code
                HAVING COUNT(*) FILTER (WHERE nav IS NULL OR nav <= 0) > 0
                ORDER BY missing DESC
            """)
            funds = [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]
    finally:
        hdb._pool.putconn(conn)

    if not funds:
        logger.info("NAV backfill: nothing to do")
        return {"status": "done", "funds_processed": 0, "nav_updated": 0}

    total = len(funds)
    updated = 0
    nav_total = 0
    logger.info("NAV backfill: %d funds need NAV data", total)

    for idx, (code, beg, end, missing) in enumerate(funds):
        try:
            navs = _fetch_nav_history(code, beg, end)
            if not navs:
                if progress_callback:
                    progress_callback(idx + 1, total, code, 0)
                continue

            # 更新 daily_kline 中的 NAV 和 premium_rate
            conn2 = hdb._pool.getconn()
            try:
                with conn2.cursor() as cur:
                    count = 0
                    for dt, nv in navs.items():
                        cur.execute(
                            """
                            UPDATE daily_kline
                            SET nav = %s,
                                premium_rate = CASE WHEN price > 0
                                    THEN ROUND((price - %s) / %s * 100, 3)
                                    ELSE premium_rate END
                            WHERE code = %s AND date = %s
                            """,
                            (nv, nv, nv, code, dt),
                        )
                        if cur.rowcount > 0:
                            count += cur.rowcount
                    conn2.commit()
                    nav_total += count
            finally:
                hdb._pool.putconn(conn2)

            updated += 1
            updated_count = count if 'count' in locals() else 0
            if progress_callback:
                progress_callback(idx + 1, total, code, nav_total)

            time.sleep(DELAY)

            if (idx + 1) % 20 == 0:
                logger.info("NAV backfill: %d/%d funds, %d NAV rows updated",
                           idx + 1, total, nav_total)
        except Exception as e:
            logger.warning("NAV backfill error for %s: %s", code, e)
            time.sleep(0.5)

    logger.info("NAV backfill complete: %d/%d funds, %d NAV rows", updated, total, nav_total)
    return {"status": "done", "funds_processed": updated, "funds_total": total, "nav_updated": nav_total}
