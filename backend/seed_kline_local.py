# -*- coding: utf-8 -*-
"""
本地K线数据补填脚本
直接从中国IP调用东方财富API，数据写入Railway PostgreSQL
避免Railway US IP被东方财富限流的问题

用法: python seed_kline_local.py
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "yamabiko.proxy.rlwy.net"),
    "port": int(os.getenv("DB_PORT", "53799")),
    "dbname": os.getenv("DB_NAME", "railway"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "connect_timeout": 30,
}
if not DB_CONFIG["password"]:
    print("Error: DB_PASSWORD environment variable is required")
    sys.exit(1)

DAYS_LOOKBACK = 395
BATCH_SIZE = 500

def _make_session():
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist={502, 503, 504, 429})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=30)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def _safe_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _market_prefix(code: str) -> str:
    return "1" if code.startswith(("501", "502")) else "0"

def fetch_kline(session, code, beg_date, end_date):
    """获取基金K线数据"""
    market = _market_prefix(code)
    secid = f"{market}.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=0&beg={beg_date}&end={end_date}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "http://quote.eastmoney.com/",
        "Accept": "*/*",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("rc") != 0 or not data.get("data") or not data["data"].get("klines"):
            return {}
        result = {}
        for line in data["data"]["klines"]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            date = parts[0]
            price = _safe_float(parts[2])
            amount = _safe_float(parts[6])
            change_pct = _safe_float(parts[8])
            if price <= 0:
                continue
            result[date] = {"price": price, "amount": amount, "change_pct": change_pct}
        return result
    except Exception as e:
        return {}

def fetch_nav_history(session, code, start_date, end_date):
    """获取基金历史净值"""
    url = (
        f"https://api.fund.eastmoney.com/f10/lsjz"
        f"?fundCode={code}&pageIndex=1&pageSize=400"
        f"&startDate={start_date}&endDate={end_date}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://fund.eastmoney.com/",
        "Accept": "*/*",
    }
    try:
        resp = session.get(url, headers=headers, timeout=10)
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
        return {}

def fetch_sse_codes(session):
    """获取上交所LOF代码"""
    codes = []
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
            resp = session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "http://quote.eastmoney.com/"}, timeout=10)
            text = resp.text.strip()
            data = json.loads(text)
            items = (data.get("data") or {}).get("diff", [])
            for item in items:
                c = str(item.get("f12", "")).strip()
                if c.startswith(("501", "502")) and c not in codes:
                    codes.append(c)
            total = (data.get("data") or {}).get("total", 0)
            if len(codes) >= total:
                break
            time.sleep(0.1)
        except Exception:
            break
    return codes

def main():
    print("=" * 60)
    print("  K线数据本地补填 (直连Railway PostgreSQL)")
    print("=" * 60)

    # ── 1. 连接数据库 ──
    print("\n[DB] Connecting to Railway PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    print(f"   已连接 {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}")

    # 确保表和索引存在
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_kline (
                date         DATE         NOT NULL,
                code         VARCHAR(6)   NOT NULL,
                price        NUMERIC(12,4),
                nav          NUMERIC(12,4),
                amount       NUMERIC(16,2) DEFAULT 0,
                change_pct   NUMERIC(10,4) DEFAULT 0,
                premium_rate NUMERIC(10,4),
                created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                PRIMARY KEY (date, code)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_kline_code_date
                ON daily_kline (code, date DESC)
        """)
    conn.commit()
    print("   表结构已就绪")

    # ── 2. 获取所有LOF代码 ──
    session = _make_session()

    sz_codes = []
    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sz_lof_codes.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            sz_codes = [k for k in json.load(f).keys() if not k.startswith("_")]

    print(f"\n[Codes] SZ LOF: {len(sz_codes)}")
    print("   Fetching SH LOF codes...")
    sse_codes = fetch_sse_codes(session)
    print(f"   SH LOF: {len(sse_codes)} 只")

    all_codes = list(set(sz_codes + sse_codes))
    print(f"   总计: {len(all_codes)} 只基金")

    # ── 3. 计算日期范围 ──
    end_dt = datetime.now()
    beg_dt = end_dt - timedelta(days=DAYS_LOOKBACK)
    beg_ymd = beg_dt.strftime("%Y%m%d")
    end_ymd = end_dt.strftime("%Y%m%d")
    beg_dash = beg_dt.strftime("%Y-%m-%d")
    end_dash = end_dt.strftime("%Y-%m-%d")
    print(f"   日期范围: {beg_dash} ~ {end_dt.strftime('%Y-%m-%d')}")

    # ── 4. 流式抓取 + 即时写入 ──
    print(f"\n 开始流式抓取 (逐基金)...")
    total = len(all_codes)
    total_rows = 0
    session_k = _make_session()
    session_n = _make_session()
    start_time = time.time()

    for idx, code in enumerate(all_codes):
        try:
            kline = fetch_kline(session_k, code, beg_ymd, end_ymd)
            if not kline:
                continue
            navs = fetch_nav_history(session_n, code, beg_dash, end_dash)
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
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur,
                        """
                        INSERT INTO daily_kline
                            (date, code, price, nav, amount, change_pct, premium_rate)
                        VALUES %s
                        ON CONFLICT (date, code) DO UPDATE SET
                            price        = EXCLUDED.price,
                            nav          = EXCLUDED.nav,
                            amount       = EXCLUDED.amount,
                            change_pct   = EXCLUDED.change_pct,
                            premium_rate = EXCLUDED.premium_rate,
                            created_at   = NOW()
                        """,
                        rows,
                        page_size=BATCH_SIZE,
                    )
                conn.commit()
                total_rows += len(rows)
        except Exception as e:
            print(f"   [WARN] {code} 失败: {e}")
            conn.rollback()

        if (idx + 1) % 50 == 0:
            elapsed = time.time() - start_time
            eta = elapsed / (idx + 1) * (total - idx - 1)
            print(f"   [{idx+1}/{total}] {total_rows} 行已保存 | 耗时 {elapsed:.0f}s | 预计剩余 {eta:.0f}s")

    # ── 5. 清理过期数据 ──
    cutoff = (datetime.now() - timedelta(days=510)).strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_kline WHERE date < %s", (cutoff,))
        if cur.rowcount > 0:
            conn.commit()
            print(f"\n 清理 {cur.rowcount} 行过期数据 (早于 {cutoff})")

    # ── 6. 完成 ──
    elapsed = time.time() - start_time
    conn.close()
    print(f"\n 完成! {total_rows} 行数据已写入 daily_kline")
    print(f"   总耗时: {elapsed:.0f}s ({elapsed/60:.1f}分钟)")
    print(f"   覆盖 {total} 只基金")

if __name__ == "__main__":
    main()
