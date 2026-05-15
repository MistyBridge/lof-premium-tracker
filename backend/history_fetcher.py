# -*- coding: utf-8 -*-
"""
LOF基金历史数据抓取模块

从东方财富API获取过去N个交易日的LOF基金历史价格和净值，
计算溢价率并保存到history_db。

数据源:
  - K线API: push2his.eastmoney.com (场内历史价格+成交额)
  - 净值API: api.fund.eastmoney.com (历史净值)

用途:
  - Railway重启后PostgreSQL数据丢失时自动补填历史数据
  - 手动初始化7天历史数据
"""
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


# ── 市场前缀映射 ────────────────────────────────
def _market_prefix(code: str) -> str:
    """东方财富 secid 市场前缀: SZ=0, SH=1"""
    if code.startswith(("501", "502")):
        return "1"  # 上交所
    return "0"  # 深交所


def _make_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=3, backoff_factor=1.0, status_forcelist={502, 503, 504, 429})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=60)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


_KLINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://quote.eastmoney.com/",
    "Accept": "*/*",
}

_NAV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://fund.eastmoney.com/",
    "Accept": "*/*",
}

_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _jparse(text: str) -> dict:
    """Parse JSONP or JSON response from East Money API"""
    text = text.strip()
    m = re.search(r"^jQuery\s*\((.+)\)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip().rstrip(";").rstrip(")")
        return json.loads(raw)
    return json.loads(text)


# ── K线数据抓取 ──────────────────────────────────

def fetch_kline_data(session: requests.Session, code: str, beg_date: str, end_date: str) -> Dict[str, dict]:
    """
    获取单只基金的日K线数据。
    返回: { "2026-04-30": {"price": 3.689, "amount": 11822.9, "change_pct": -0.03, "name": "..."}, ... }
    
    K线字段: 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
    """
    market = _market_prefix(code)
    secid = f"{market}.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=0&beg={beg_date}&end={end_date}"
    )
    try:
        resp = session.get(url, headers=_KLINE_HEADERS, timeout=10)
        data = resp.json()
        if data.get("rc") != 0 or not data.get("data") or not data["data"].get("klines"):
            return {}

        result = {}
        name = data["data"].get("name", "")
        for line in data["data"]["klines"]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            date = parts[0]
            price = _safe_float(parts[2])  # 收盘价
            amount = _safe_float(parts[6])  # 成交额
            change_pct = _safe_float(parts[8])  # 涨跌幅
            if price <= 0:
                continue
            result[date] = {
                "price": price,
                "amount": amount,
                "change_pct": change_pct,
                "name": name,
            }
        return result
    except Exception as e:
        logger.debug(f"K-line fetch failed for {code}: {e}")
        return {}


def fetch_kline_tencent(session: requests.Session, code: str) -> Dict[str, dict]:
    """
    腾讯QT K线API备源。返回格式同 fetch_kline_data。
    """
    prefix = "sh" if code.startswith(("501", "502")) else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,400"
    try:
        resp = session.get(url, headers=_KLINE_HEADERS, timeout=10)
        data = resp.json()
        klines = (data.get("data") or {}).get(f"{prefix}{code}", {}).get("day", []) or \
                 (data.get("data") or {}).get(f"{prefix}{code}", {}).get("qfqday", [])
        if not klines:
            return {}
        result = {}
        for line in klines:
            if len(line) < 6:
                continue
            date = line[0]
            price = _safe_float(line[2])  # close
            amount = _safe_float(line[5]) * 100  # volume * 100 = 成交额(元)
            change_pct = 0
            if price <= 0:
                continue
            result[date] = {"price": price, "amount": amount, "change_pct": change_pct}
        return result
    except Exception as e:
        logger.debug(f"Tencent K-line failed for {code}: {e}")
        return {}


def fetch_kline_multisource(session: requests.Session, code: str,
                             beg_date: str, end_date: str) -> Dict[str, dict]:
    """
    多源K线数据抓取：依次尝试 EastMoney → 腾讯QT，返回第一个有数据的。
    """
    # Source 1: East Money push2his (primary, most complete)
    result = fetch_kline_data(session, code, beg_date, end_date)
    if result:
        return result

    # Source 2: Tencent QT (backup)
    result = fetch_kline_tencent(session, code)
    if result:
        # Filter by date range
        filtered = {d: v for d, v in result.items() if beg_date[:4] <= d[:4] <= end_date[:4]}
        if filtered:
            return filtered

    return {}


# ── 净值历史抓取 ──────────────────────────────────

def fetch_nav_history(session: requests.Session, code: str, start_date: str, end_date: str) -> Dict[str, float]:
    """
    获取单只基金的历史净值。
    返回: { "2026-04-30": 3.7954, "2026-04-29": 3.8107, ... }
    
    日期格式: YYYY-MM-DD
    """
    url = (
        f"https://api.fund.eastmoney.com/f10/lsjz"
        f"?fundCode={code}&pageIndex=1&pageSize=15"
        f"&startDate={start_date}&endDate={end_date}"
    )
    try:
        resp = session.get(url, headers=_NAV_HEADERS, timeout=10)
        data = resp.json()
        lsjz_list = (data.get("Data") or {}).get("LSJZList") or []
        result = {}
        for item in lsjz_list:
            date = item.get("FSRQ")
            nav_str = item.get("DWJZ")
            if date and nav_str:
                nav = _safe_float(nav_str)
                if nav > 0:
                    result[date] = nav
        return result
    except Exception as e:
        logger.debug(f"NAV history fetch failed for {code}: {e}")
        return {}


# ── SSE LOF代码列表 ──────────────────────────────

def _fetch_sse_lof_codes(session: requests.Session) -> List[str]:
    """从东方财富push2delay获取上交所LOF代码列表"""
    sse_codes = []
    for pn in range(1, 25):
        url = (
            "https://push2delay.eastmoney.com/api/qt/clist/get"
            f"?pn={pn}&pz=100&po=1&np=1"
            f"&ut=bd1d9ddb04089700cf9c27f6f7426281"
            f"&fltt=2&invt=2&fid=f3"
            f"&fs=m:1+t:9"
            f"&fields=f12,f14"
        )
        try:
            resp = session.get(url, headers=_EM_HEADERS, timeout=10)
            data = _jparse(resp.text)
            items = (data.get("data") or {}).get("diff", [])
            for item in items:
                code = str(item.get("f12", "")).strip()
                if code.startswith(("501", "502")) and code not in sse_codes:
                    sse_codes.append(code)
            total = (data.get("data") or {}).get("total", 0)
            if len(sse_codes) >= total:
                break
            time.sleep(0.1)
        except Exception as e:
            logger.warning(f"SSE code fetch page {pn} failed: {e}")
            break
    return sse_codes


# ── 主函数 ───────────────────────────────────────

def fetch_historical_data(days: int = 7) -> int:
    """
    获取过去N个交易日的LOF基金历史数据并保存到history_db。
    用于Railway重启后自动补填历史数据。
    
    返回: 保存的总行数
    """
    from history_db import get_history_db
    from datasource.manager import get_datasource_manager
    ds = get_datasource_manager()

    # 计算日期范围（15个自然日覆盖7个交易日）
    end_dt = datetime.now()
    beg_dt = end_dt - timedelta(days=15)
    # K线API用YYYYMMDD格式
    beg_ymd = beg_dt.strftime("%Y%m%d")
    end_ymd = end_dt.strftime("%Y%m%d")
    # 净值API用YYYY-MM-DD格式
    beg_dash = beg_dt.strftime("%Y-%m-%d")
    end_dash = end_dt.strftime("%Y-%m-%d")

    # ── 1. 获取所有LOF代码 ──
    # SZ codes from sz_lof_codes.json
    sz_codes = []
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sz_lof_codes.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                sz_codes = [k for k in json.load(f).keys() if not k.startswith("_")]
        except Exception as e:
            logger.warning(f"Failed to load sz_lof_codes.json: {e}")

    # SSE codes from push2delay
    session = _make_session()
    logger.info("Fetching SSE LOF codes...")
    sse_codes = _fetch_sse_lof_codes(session)
    
    all_codes = sz_codes + sse_codes
    logger.info(f"Total LOF codes: {len(all_codes)} (SZ: {len(sz_codes)}, SH: {len(sse_codes)})")

    # ── 2. 逐基金抓取K线+净值 ──
    # 按日期收集结果: date -> { code -> fund_data }
    by_date: Dict[str, Dict[str, dict]] = {}
    by_date_lock = threading.Lock()
    sem = threading.Semaphore(8)  # 8并发，避免限流
    total = len(all_codes)
    processed = [0]  # mutable counter

    def process_one(code: str):
        with sem:
            try:
                # 使用数据源管理器（AkShare → Legacy 降级）
                kline = ds.fetch_kline(code, beg_ymd, end_ymd)
                navs = ds.fetch_nav_history(code, beg_dash, end_dash)

                if not kline:
                    return

                for date_str, price_info in kline.items():
                    # K线返回的日期格式: YYYY-MM-DD
                    nav = navs.get(date_str)
                    price = price_info["price"]
                    amount = price_info["amount"]
                    name = price_info.get("name", "")
                    change_pct = price_info.get("change_pct", 0)

                    premium_rate = None
                    if nav and nav > 0 and price > 0:
                        premium_rate = round((price - nav) / nav * 100, 3)

                    fund_data = {
                        "code": code,
                        "name": name,
                        "price": price,
                        "nav": nav,
                        "amount": amount,
                        "premium_rate": premium_rate,
                        "change_pct": change_pct,
                    }

                    with by_date_lock:
                        if date_str not in by_date:
                            by_date[date_str] = {}
                        by_date[date_str][code] = fund_data
            except Exception as e:
                logger.debug(f"Process {code} failed: {e}")
            finally:
                processed[0] += 1
                if processed[0] % 50 == 0:
                    logger.info(f"History progress: {processed[0]}/{total}")

    # 分批处理
    batch_size = 40
    for i in range(0, total, batch_size):
        batch = all_codes[i:i + batch_size]
        threads = []
        for code in batch:
            t = threading.Thread(target=process_one, args=(code,))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        # 批间暂停，避免触发限流
        time.sleep(0.8)

    logger.info(f"History fetch complete: {processed[0]}/{total} funds processed")

    # ── 3. 保存到 history_db ──
    hdb = get_history_db()
    total_rows = 0

    for date_str in sorted(by_date.keys()):
        funds = by_date[date_str]
        hdb.save_snapshot(funds, date=date_str)
        total_rows += len(funds)
        logger.info(f"  Saved {date_str}: {len(funds)} funds")

    logger.info(f"✅ Historical data saved: {total_rows} rows across {len(by_date)} dates")
    return total_rows


def fetch_kline_historical_data(days_lookback: int = 395) -> int:
    """
    获取过去约1年的日K线数据（价格+净值），存入 daily_kline 表。
    用于图表展示的 7日/30日/365日 数据源。

    返回: 保存的总行数
    """
    from history_db import get_history_db

    end_dt = datetime.now()
    beg_dt = end_dt - timedelta(days=days_lookback)
    beg_ymd = beg_dt.strftime("%Y%m%d")
    end_ymd = end_dt.strftime("%Y%m%d")
    beg_dash = beg_dt.strftime("%Y-%m-%d")
    end_dash = end_dt.strftime("%Y-%m-%d")

    # ── 1. 获取所有 LOF 代码 ──
    sz_codes = []
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sz_lof_codes.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                sz_codes = [k for k in json.load(f).keys() if not k.startswith("_")]
        except Exception as e:
            logger.warning(f"Failed to load sz_lof_codes.json: {e}")

    session = _make_session()
    logger.info("Fetching SSE LOF codes for kline...")
    sse_codes = _fetch_sse_lof_codes(session)

    all_codes = list(set(sz_codes + sse_codes))
    logger.info(f"Kline history: {len(all_codes)} codes (SZ:{len(sz_codes)} SH:{len(sse_codes)})")

    # ── 2. 流式逐基金抓取 + 即时保存 ──
    from datasource.manager import get_datasource_manager
    ds = get_datasource_manager()
    hdb = get_history_db()
    total = len(all_codes)
    total_rows = 0

    session_k = _make_session()

    for idx, code in enumerate(all_codes):
        try:
            # 多源K线: EastMoney → Tencent → AkShare
            kline = fetch_kline_multisource(session_k, code, beg_ymd, end_ymd)
            if not kline:
                # 多源都失败，尝试datasource manager作为最后手段
                kline = ds.fetch_kline(code, beg_ymd, end_ymd)
            if not kline:
                continue
            navs = ds.fetch_nav_history(code, beg_dash, end_dash)
            rows = []
            for date_str, info in kline.items():
                nav = navs.get(date_str)
                price = info["price"]
                amount = info.get("amount", 0)
                change_pct = info.get("change_pct", 0)
                premium_rate = None
                if nav and nav > 0 and price > 0:
                    premium_rate = round((price - nav) / nav * 100, 3)
                rows.append((
                    date_str, code, price, nav, amount,
                    change_pct, premium_rate
                ))
            if rows:
                hdb.save_kline_batch(rows)
                total_rows += len(rows)
        except Exception as e:
            logger.warning("Kline fetch failed for %s: %s", code, e)

        if (idx + 1) % 50 == 0:
            logger.info("Kline streaming: %d/%d funds, %d rows saved",
                         idx + 1, total, total_rows)

    logger.info("Kline streaming complete: %d/%d funds, %d rows saved",
                 total, total, total_rows)
    return total_rows
