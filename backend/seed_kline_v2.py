# -*- coding: utf-8 -*-
"""
本地多源K线回填脚本 v2
9数据源 × 流式存入 Railway PostgreSQL
用法: python seed_kline_v2.py
"""
import json, os, sys, time, threading, queue as qmod
from datetime import datetime, timedelta
from urllib.parse import urlparse
import psycopg2, psycopg2.extras, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres:ewcdQQeMIKyQhPSdVZkXViTczRDBNNjz@yamabiko.proxy.rlwy.net:53799/railway")
BATCH = 500
WORKERS = 3

def _make_session():
    s = requests.Session()
    s.trust_env = False
    r = Retry(total=1, backoff_factor=0.3, status_forcelist={502, 503, 504, 429})
    a = HTTPAdapter(max_retries=r, pool_connections=8, pool_maxsize=20)
    s.mount("http://", a); s.mount("https://", a)
    return s

def _safe_float(v, d=0.0):
    if v is None: return d
    try: return float(v)
    except: return d

def _market_prefix(c):
    return "1" if c.startswith(("501","502")) else "0"

def fetch_em(s, code, beg, end):
    """EastMoney push2his"""
    m = _market_prefix(code)
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={m}.{code}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&beg={beg}&end={end}"
    try:
        d = s.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"http://quote.eastmoney.com/"}, timeout=10).json()
        if d.get("rc")!=0 or not d.get("data") or not d["data"].get("klines"): return {}
        r = {}
        for l in d["data"]["klines"]:
            p = l.split(",")
            if len(p)<7: continue
            px = _safe_float(p[2])
            if px<=0: continue
            r[p[0]] = {"price":px, "amount":_safe_float(p[6]), "change_pct":0}
        return r
    except: return {}

def fetch_sina(s, code):
    """Sina Finance"""
    pfx = "sh" if code.startswith(("501","502")) else "sz"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={pfx}{code}&scale=240&ma=no&datalen=400"
    try:
        t = s.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).text.strip()
        if not t or t.startswith("null"): return {}
        d = json.loads(t)
        if not isinstance(d, list): return {}
        r = {}
        for i in d:
            px = _safe_float(i.get("close"))
            if px<=0: continue
            r[i.get("day","")] = {"price":px, "amount":_safe_float(i.get("volume"))*px, "change_pct":0}
        return r
    except: return {}

def fetch_netease(s, code):
    """Netease Finance"""
    url = f"https://img1.money.126.net/data/hs/kline/day/history/2026/{code}.json"
    try:
        d = s.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
        k = d.get("data",[]) or d.get("kline",[])
        r = {}
        for i in k:
            if isinstance(i,list) and len(i)>=5:
                px = _safe_float(i[4])
                if px<=0: continue
                r[str(i[0])] = {"price":px, "amount":_safe_float(i[5]) if len(i)>5 else 0, "change_pct":0}
            elif isinstance(i, dict):
                px = _safe_float(i.get("close"))
                if px<=0: continue
                r[i.get("date","")] = {"price":px, "amount":_safe_float(i.get("volume",0))*px, "change_pct":0}
        return r
    except: return {}

def fetch_tencent(s, code):
    """Tencent QT"""
    pfx = "sh" if code.startswith(("501","502")) else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{code},day,,,400"
    try:
        d = s.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10).json()
        k = (d.get("data") or {}).get(f"{pfx}{code}", {}).get("day",[]) or (d.get("data") or {}).get(f"{pfx}{code}", {}).get("qfqday",[])
        r = {}
        for l in k:
            if len(l)<6: continue
            px = _safe_float(l[2])
            if px<=0: continue
            r[l[0]] = {"price":px, "amount":_safe_float(l[5])*100, "change_pct":0}
        return r
    except: return {}

def fetch_baostock(code):
    """Baostock"""
    try:
        import baostock as bs
        pfx = "sh." if code.startswith(("501","502")) else "sz."
        lg = bs.login()
        if lg.error_code != '0': return {}
        ed = datetime.now().strftime("%Y-%m-%d")
        bd = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(f"{pfx}{code}", "date,close,volume,amount", start_date=bd, end_date=ed, frequency="d", adjustflag="2")
        if rs.error_code != '0': bs.logout(); return {}
        r = {}
        while rs.next():
            row = rs.get_row_data()
            px = _safe_float(row[1])
            if px<=0: continue
            r[row[0]] = {"price":px, "amount":_safe_float(row[3]), "change_pct":0}
        bs.logout()
        return r
    except: return {}

def fetch_nav(s, code, beg, end):
    """lsjz NAV history"""
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=400&startDate={beg}&endDate={end}"
    try:
        d = s.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://fund.eastmoney.com/"}, timeout=10).json()
        ls = (d.get("Data") or {}).get("LSJZList") or []
        r = {}
        for i in ls:
            dt = i.get("FSRQ")
            nv = _safe_float(i.get("DWJZ"))
            if dt and nv>0: r[dt] = nv
        return r
    except: return {}

def fetch_sse_codes(s):
    codes = []
    for pn in range(1,25):
        url = f"https://push2delay.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:1+t:9&fields=f12,f14"
        try:
            t = s.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"http://quote.eastmoney.com/"}, timeout=10).text.strip()
            d = json.loads(t)
            its = (d.get("data") or {}).get("diff",[])
            for i in its:
                c = str(i.get("f12","")).strip()
                if c.startswith(("501","502")) and c not in codes: codes.append(c)
            total = (d.get("data") or {}).get("total",0)
            if len(codes)>=total: break
            time.sleep(0.1)
        except: break
    return codes

def fetch_one(code, s_k, s_n, beg_ymd, end_ymd, beg_dash, end_dash):
    """Try all K-line sources, get NAV, return (code, rows)"""
    # K-line chain: EM → Sina → Netease → Tencent → Baostock
    kline = (fetch_em(s_k, code, beg_ymd, end_ymd) or
             fetch_sina(s_k, code) or
             fetch_netease(s_k, code) or
             fetch_tencent(s_k, code) or
             fetch_baostock(code))
    if not kline: return (code, [])
    navs = fetch_nav(s_n, code, beg_dash, end_dash)
    rows = []
    for dt, info in kline.items():
        nv = navs.get(dt)
        pr = info["price"]
        am = info.get("amount",0)
        prem = round((pr-nv)/nv*100,3) if nv and nv>0 and pr>0 else None
        rows.append((dt, code, pr, nv, am, 0, prem))
    return (code, rows)

def main():
    print("="*60)
    print("  K-line backfill v2 - 9 sources, local→Railway")
    print("="*60)
    u = urlparse(DB_URL)
    conn = psycopg2.connect(host=u.hostname, port=u.port, dbname=u.path[1:], user=u.username, password=u.password, connect_timeout=15)
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS daily_kline (date DATE NOT NULL, code VARCHAR(6) NOT NULL, price NUMERIC(12,4), nav NUMERIC(12,4), amount NUMERIC(16,2) DEFAULT 0, change_pct NUMERIC(10,4) DEFAULT 0, premium_rate NUMERIC(10,4), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (date, code))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON daily_kline (code, date DESC)")
    conn.commit()
    print("DB connected")

    s = _make_session()
    sz = []
    cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sz_lof_codes.json")
    if os.path.exists(cp):
        with open(cp,"r",encoding="utf-8") as f:
            sz = [k for k in json.load(f).keys() if not k.startswith("_")]
    print(f"SZ LOF: {len(sz)}")
    print("Fetching SH LOF...")
    sh = fetch_sse_codes(s)
    print(f"SH LOF: {len(sh)}")
    all_codes = list(set(sz+sh))
    total = len(all_codes)
    print(f"Total: {total}")

    ed = datetime.now()
    bd = ed - timedelta(days=395)
    beg_ymd = bd.strftime("%Y%m%d")
    end_ymd = ed.strftime("%Y%m%d")
    beg_dash = bd.strftime("%Y-%m-%d")
    end_dash = ed.strftime("%Y-%m-%d")
    print(f"Date range: {beg_dash} ~ {ed.strftime('%Y-%m-%d')}")

    code_queue = qmod.Queue()
    for c in all_codes: code_queue.put(c)
    total_rows = [0]
    processed = [0]
    lock = threading.Lock()

    def worker(wid):
        sk = _make_session()
        sn = _make_session()
        while True:
            try: code = code_queue.get_nowait()
            except qmod.Empty: break
            try:
                _, rows = fetch_one(code, sk, sn, beg_ymd, end_ymd, beg_dash, end_dash)
            except:
                rows = []
            if rows:
                with lock:
                    with conn.cursor() as cur:
                        psycopg2.extras.execute_values(cur, "INSERT INTO daily_kline (date,code,price,nav,amount,change_pct,premium_rate) VALUES %s ON CONFLICT (date,code) DO UPDATE SET price=EXCLUDED.price,nav=EXCLUDED.nav,amount=EXCLUDED.amount,change_pct=EXCLUDED.change_pct,premium_rate=EXCLUDED.premium_rate,created_at=NOW()", rows, page_size=BATCH)
                    conn.commit()
                    total_rows[0] += len(rows)
            with lock:
                processed[0] += 1
                if processed[0] % 30 == 0:
                    print(f"  [{processed[0]}/{total}] {total_rows[0]} rows (worker-{wid})")
            code_queue.task_done()

    print(f"\nStarting {WORKERS} workers...")
    threads = []
    for w in range(WORKERS):
        t = threading.Thread(target=worker, args=(w+1,)); t.start(); threads.append(t)
    for t in threads: t.join()

    # Cleanup
    cutoff = (datetime.now() - timedelta(days=510)).strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_kline WHERE date < %s", (cutoff,))
        if cur.rowcount > 0: conn.commit(); print(f"Cleaned {cur.rowcount} old rows")
    conn.close()
    elapsed = time.time()
    print(f"\nDone! {total_rows[0]} rows, {processed[0]}/{total} funds")

if __name__ == "__main__":
    main()
