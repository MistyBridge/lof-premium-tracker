#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取剩余基金的日线数据（使用腾讯财经API）
虽然缺少成交额、涨跌幅、换手率，但可以计算涨跌幅
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置
LOF_CODES_FILE = Path(__file__).parent / "backend" / "sz_lof_codes.json"
OUTPUT_FILE = Path(__file__).parent / "data" / "lof_kline_remaining.json"

def make_session():
    s = requests.Session()
    s.trust_env = False
    retry = Retry(total=2, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def safe_float(val, default=0.0):
    try:
        return float(val)
    except:
        return default

def fetch_kline_tencent(session, code):
    """腾讯财经API获取K线数据"""
    prefix = "sh" if code.startswith(("501", "502")) else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,400,qfq"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        resp = session.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        stock_data = (data.get("data") or {}).get(f"{prefix}{code}", {})
        klines = stock_data.get("day", []) or stock_data.get("qfqday", [])
        
        if not klines:
            return {}
        
        result = {}
        prev_close = None
        
        for line in klines:
            if len(line) < 6:
                continue
            
            date = line[0]
            open_price = safe_float(line[1])
            close = safe_float(line[2])
            high = safe_float(line[3])
            low = safe_float(line[4])
            volume = safe_float(line[5])
            
            if close <= 0:
                continue
            
            # 计算涨跌幅
            change_pct = None
            if prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 4)
            
            result[date] = {
                "price": close,
                "open": open_price,
                "high": high,
                "low": low,
                "volume": int(volume),
                "change_pct": change_pct,
                "source": "tencent"
            }
            
            prev_close = close
        
        return result
    except Exception as e:
        return {}

def load_lof_codes():
    with open(LOF_CODES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.keys())

def load_existing_codes():
    """加载已入库的基金代码"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='101.200.129.61',
            port=5432,
            database='jinkuaicha',
            user='deploy',
            password='<REDACTED-PASSWORD>',
            connect_timeout=10
        )
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT code FROM daily_kline;")
        codes = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return set(codes)
    except:
        return set()

def save_results(results):
    output = {
        "metadata": {
            "fetch_time": datetime.now().isoformat(),
            "source": "tencent",
            "total_funds": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
        },
        "data": {r["code"]: r["data"] for r in results if r["status"] == "success"}
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

def main():
    print("=" * 60)
    print("获取剩余基金日线数据（腾讯财经API）")
    print("=" * 60)
    
    # 加载LOF代码
    lof_codes = load_lof_codes()
    print(f"LOF基金总数: {len(lof_codes)}")
    
    # 加载已入库的代码
    existing_codes = load_existing_codes()
    print(f"已入库: {len(existing_codes)} 只")
    
    # 计算需要获取的代码
    remaining_codes = [c for c in lof_codes if c not in existing_codes]
    print(f"待获取: {len(remaining_codes)} 只")
    
    if not remaining_codes:
        print("所有基金数据已入库")
        return
    
    session = make_session()
    
    # 获取数据
    print(f"\n开始获取 {len(remaining_codes)} 只基金的数据...")
    all_results = []
    success_count = 0
    fail_count = 0
    
    start_time = time.time()
    
    for i, code in enumerate(remaining_codes, 1):
        print(f"[{i}/{len(remaining_codes)}] {code}...", end=" ")
        data = fetch_kline_tencent(session, code)
        count = len(data) if data else 0
        status = "success" if count > 50 else "no_data"
        all_results.append({"code": code, "data": data or {}, "count": count, "status": status})
        
        if count > 50:
            success_count += 1
            print(f"{count} 条")
        else:
            fail_count += 1
            print(f"NO DATA")
        
        if i % 50 == 0:
            save_results(all_results)
            print(f"  -> 已保存中间结果")
        
        time.sleep(0.2)
    
    elapsed = time.time() - start_time
    
    save_results(all_results)
    
    print("\n" + "=" * 60)
    print("获取完成！")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    print(f"成功率: {success_count/len(remaining_codes)*100:.1f}%")
    print(f"耗时: {elapsed:.1f} 秒")
    print(f"输出文件: {OUTPUT_FILE}")
    print("=" * 60)
    print("\n注意: 腾讯API数据缺少成交额、换手率，但包含涨跌幅（计算得出）")

if __name__ == "__main__":
    main()
