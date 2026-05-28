# -*- coding: utf-8 -*-
"""
十大持仓缓存模块
- 数据在后台定时刷新时预抓取，不在用户请求时实时请求
- 缓存到磁盘，季度数据变化频率极低
"""
import json
import logging
import os
import re
import threading
import time

import requests as req

logger = logging.getLogger(__name__)

_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings_cache.json")
_lock = threading.Lock()
_cache: dict = {}          # {code: {holdings, quarter, updated_at}}
_last_refresh: float = 0


def _fetch_raw(code: str) -> dict | None:
    """从东方财富抓取原始持仓数据（内部调用，不在用户请求时触发）"""
    try:
        url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10"
        resp = req.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://fundf10.eastmoney.com/ccmx_{code}.html"
        }, timeout=10)
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        start = html.find('content:"')
        if start < 0:
            return None
        start += 9
        end = html.find('",', start)
        if end < 0:
            return None
        content = html[start:end].replace('\\"', '"').replace('\\/', '/')

        holdings = []
        for m in re.finditer(r'<tr>(.*?)</tr>', content, re.DOTALL):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', m.group(1), re.DOTALL)
            if len(cells) < 9:
                continue
            rank = re.sub(r'<[^>]+>', '', cells[0]).strip()
            if not rank.isdigit():
                continue
            pct = re.sub(r'<[^>]+>', '', cells[6]).strip()
            if not pct or pct == '--':
                continue
            holdings.append({
                "rank": int(rank),
                "code": re.sub(r'<[^>]+>', '', cells[1]).strip(),
                "name": re.sub(r'<[^>]+>', '', cells[2]).strip(),
                "pct": pct,
                "shares": re.sub(r'<[^>]+>', '', cells[7]).strip(),
                "market_value": re.sub(r'<[^>]+>', '', cells[8]).strip(),
            })

        quarter_match = re.search(r'(\d{4})年(\d)季度', html)
        quarter = f"{quarter_match.group(1)}Q{quarter_match.group(2)}" if quarter_match else None

        return {"holdings": holdings[:10], "quarter": quarter}
    except Exception as e:
        logger.warning(f"holdings_fetch_failed code={code} error={e}")
        return None


def load_cache() -> dict:
    """加载磁盘缓存"""
    global _cache, _last_refresh
    try:
        if os.path.exists(_CACHE_PATH):
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _cache = data.get("data", {})
            _last_refresh = data.get("ts", 0)
    except Exception:
        pass
    return _cache


def save_cache() -> None:
    """保存到磁盘"""
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "data": _cache}, f, ensure_ascii=False)
    except Exception:
        pass


def get_holdings(code: str) -> dict | None:
    """读取缓存中的持仓数据"""
    with _lock:
        return _cache.get(code)


def refresh_for_funds(funds: dict) -> int:
    """
    后台定时刷新：为符合条件的基金预抓取持仓数据
    每次刷新前清除旧缓存
    """
    global _cache, _last_refresh
    _cache = {}
    fetched = 0
    now = time.time()

    for code, fund in funds.items():
        # 条件筛选
        if fund.get("is_suspended"):
            continue
        if fund.get("can_purchase") in (False, 0, 0.0):
            continue
        amount = fund.get("amount") or 0
        if amount < 1_000_000:
            continue

        data = _fetch_raw(code)
        if data and data.get("holdings"):
            data["updated_at"] = now
            with _lock:
                _cache[code] = data
            fetched += 1
            time.sleep(0.3)  # 请求间隔，避免被限流

    if fetched > 0:
        _last_refresh = now
        save_cache()
        logger.info(f"holdings_refreshed count={fetched}")

    return fetched


# 模块加载时读缓存
load_cache()
