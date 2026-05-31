#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOF基金日线数据导出工具（多数据源）
支持：新浪财经、腾讯财经、东方财富
"""
import json
import os
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
OUTPUT_FILE = Path(__file__).parent / "data" / "lof_kline_data.json"
SAMPLE_SIZE = 10

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

def fetch_kline_sina(session, code):
    """新浪财经API"""
    prefix = "sh" if code.startswith(("501", "502")) else "sz"
    symbol = f"{prefix}{code}"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=400"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
    try:
        resp = session.get(url, headers=headers, timeout=10)
        text = resp.text.strip()
        if not text or text.startswith("null"):
            return {}
        data = json.loads(text)
        if not isinstance(data, list):
            return {}
        result = {}
        for item in data:
            date = item.get("day", "")
            close = safe_float(item.get("close"))
            if close <= 0:
                continue
            result[date] = {
                "price": close,
                "open": safe_float(item.get("open")),
                "high": safe_float(item.get("high")),
                "low": safe_float(item.get("low")),
                "volume": int(safe_float(item.get("volume"))),
                "source": "sina"
            }
        return result
    except:
        return {}

def fetch_kline_tencent(session, code):
    """腾讯财经API"""
    prefix = "sh" if code.startswith(("501", "502")) else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,400"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = session.get(url, headers=headers, timeout=10)
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
            close = safe_float(line[2])
            volume = safe_float(line[5])
            if close <= 0:
                continue
            result[date] = {
                "price": close,
                "open": safe_float(line[1]),
                "high": safe_float(line[3]),
                "low": safe_float(line[4]),
                "volume": int(volume),
                "source": "tencent"
            }
        return result
    except:
        return {}

def fetch_kline_multi(session, code):
    """多数据源尝试"""
    # 1. 尝试新浪
    data = fetch_kline_sina(session, code)
    if data and len(data) > 100:
        return data
    
    # 2. 尝试腾讯
    data2 = fetch_kline_tencent(session, code)
    if data2 and len(data2) > len(data):
        return data2
    
    return data or data2 or {}

def load_lof_codes():
    with open(LOF_CODES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.keys())

def save_results(results):
    output = {
        "metadata": {
            "fetch_time": datetime.now().isoformat(),
            "source": "multi(sina+tencent)",
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
    print("LOF基金日线数据导出工具（多数据源）")
    print("=" * 60)
    
    lof_codes = load_lof_codes()
    print(f"LOF基金总数: {len(lof_codes)}")
    
    session = make_session()
    
    # 第一步：样本校验
    print(f"\n--- 第一步：获取 {SAMPLE_SIZE} 个样本校验 ---")
    sample_codes = lof_codes[:SAMPLE_SIZE]
    sample_results = []
    
    for i, code in enumerate(sample_codes, 1):
        print(f"[{i}/{SAMPLE_SIZE}] 获取 {code}...", end=" ")
        data = fetch_kline_multi(session, code)
        count = len(data) if data else 0
        status = "success" if count > 50 else "no_data"
        sample_results.append({"code": code, "data": data or {}, "count": count, "status": status})
        print(f"{count} 条")
        time.sleep(0.2)
    
    # 校验样本
    print("\n=== 样本数据校验 ===")
    success_count = sum(1 for r in sample_results if r["status"] == "success")
    success_rate = success_count / len(sample_results) * 100
    print(f"成功率: {success_rate:.1f}% ({success_count}/{len(sample_results)})")
    
    if success_count > 0:
        sample_data = next(r for r in sample_results if r["status"] == "success")
        dates = sorted(sample_data["data"].keys())
        print(f"数据范围: {dates[0]} ~ {dates[-1]}")
        print(f"数据条数: {len(dates)}")
    
    if success_rate < 80:
        print("\n样本校验失败，成功率不足80%")
        return
    
    print("\n样本校验通过！")
    
    # 第二步：获取全部数据
    print(f"\n--- 第二步：获取全部 {len(lof_codes)} 只基金数据 ---")
    all_results = list(sample_results)
    total_success = success_count
    total_fail = len(sample_results) - success_count
    
    start_time = time.time()
    
    for i, code in enumerate(lof_codes[len(sample_codes):], len(sample_codes) + 1):
        print(f"[{i}/{len(lof_codes)}] {code}...", end=" ")
        data = fetch_kline_multi(session, code)
        count = len(data) if data else 0
        status = "success" if count > 50 else "no_data"
        all_results.append({"code": code, "data": data or {}, "count": count, "status": status})
        if count > 50:
            total_success += 1
            print(f"{count} 条")
        else:
            total_fail += 1
            print(f"NO DATA")
        
        if i % 100 == 0:
            save_results(all_results)
            print(f"  -> 已保存中间结果")
        
        time.sleep(0.2)
    
    elapsed = time.time() - start_time
    
    save_results(all_results)
    
    print("\n" + "=" * 60)
    print("导出完成！")
    print(f"成功: {total_success}")
    print(f"失败: {total_fail}")
    print(f"成功率: {total_success/len(lof_codes)*100:.1f}%")
    print(f"耗时: {elapsed:.1f} 秒")
    print(f"输出文件: {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
