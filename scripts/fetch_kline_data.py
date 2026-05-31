#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取LOF基金日线数据脚本
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import requests
from history_fetcher import fetch_kline_data

LOF_CODES_FILE = Path(__file__).parent.parent / "backend" / "sz_lof_codes.json"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "lof_kline_data.json"
SAMPLE_SIZE = 10

def load_lof_codes():
    with open(LOF_CODES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.keys())

def fetch_single_fund(session, code, beg_date, end_date):
    try:
        data = fetch_kline_data(session, code, beg_date, end_date)
        if data:
            return {"code": code, "data": data, "count": len(data), "status": "success"}
        return {"code": code, "data": {}, "count": 0, "status": "no_data"}
    except Exception as e:
        return {"code": code, "data": {}, "count": 0, "status": "error: " + str(e)[:50]}

def validate_sample(sample_results):
    print("\n=== 样本数据校验 ===")
    success_count = 0
    for r in sample_results:
        status = "OK" if r["status"] == "success" and r["count"] > 0 else "FAIL"
        print(f"  {status} {r['code']}: {r['count']} 条数据 ({r['status']})")
        if r["status"] == "success" and r["count"] > 0:
            success_count += 1
    
    success_rate = success_count / len(sample_results) * 100
    print(f"\n成功率: {success_rate:.1f}% ({success_count}/{len(sample_results)})")
    
    if success_count > 0:
        sample_data = next(r for r in sample_results if r["status"] == "success")
        dates = sorted(sample_data["data"].keys())
        print(f"数据范围: {dates[0]} ~ {dates[-1]}")
        print(f"数据条数: {len(dates)}")
    
    return success_rate >= 80

def save_results(results, beg_date, end_date):
    output = {
        "metadata": {
            "fetch_time": datetime.now().isoformat(),
            "date_range": {"start": beg_date, "end": end_date},
            "total_funds": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
        },
        "data": {r["code"]: r["data"] for r in results if r["status"] == "success"}
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

def main():
    print("=" * 60)
    print("LOF基金日线数据获取工具")
    print("=" * 60)
    
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    lof_codes = load_lof_codes()
    print(f"\nLOF基金总数: {len(lof_codes)}")
    
    end_date = datetime.now().strftime("%Y%m%d")
    beg_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    print(f"数据范围: {beg_date} ~ {end_date}")
    
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    
    # 第一步：样本校验
    print(f"\n--- 第一步：获取 {SAMPLE_SIZE} 个样本校验 ---")
    sample_codes = lof_codes[:SAMPLE_SIZE]
    sample_results = []
    
    for i, code in enumerate(sample_codes, 1):
        print(f"[{i}/{SAMPLE_SIZE}] 获取 {code}...", end=" ")
        result = fetch_single_fund(session, code, beg_date, end_date)
        sample_results.append(result)
        print(f"{result['count']} 条")
        time.sleep(0.3)
    
    if not validate_sample(sample_results):
        print("\n样本校验失败，成功率不足80%")
        return
    
    print("\n样本校验通过！")
    
    # 第二步：获取全部数据
    print(f"\n--- 第二步：获取全部 {len(lof_codes)} 只基金数据 ---")
    all_results = list(sample_results)
    success_count = sum(1 for r in sample_results if r["status"] == "success")
    fail_count = sum(1 for r in sample_results if r["status"] != "success")
    
    start_time = time.time()
    
    for i, code in enumerate(lof_codes[len(sample_codes):], len(sample_codes) + 1):
        print(f"[{i}/{len(lof_codes)}] {code}...", end=" ")
        result = fetch_single_fund(session, code, beg_date, end_date)
        all_results.append(result)
        
        if result["status"] == "success":
            success_count += 1
            print(f"{result['count']} 条")
        else:
            fail_count += 1
            print(f"FAIL")
        
        if i % 100 == 0:
            save_results(all_results, beg_date, end_date)
            print(f"  -> 已保存中间结果")
        
        time.sleep(0.3)
    
    elapsed = time.time() - start_time
    
    save_results(all_results, beg_date, end_date)
    
    print("\n" + "=" * 60)
    print("获取完成！")
    print(f"成功: {success_count}")
    print(f"失败: {fail_count}")
    print(f"成功率: {success_count/len(lof_codes)*100:.1f}%")
    print(f"耗时: {elapsed:.1f} 秒")
    print(f"输出文件: {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
