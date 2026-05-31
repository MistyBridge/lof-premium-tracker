#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出LOF基金日线数据到本地文件
使用项目中的 history_fetcher 模块获取数据
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# 配置
LOF_CODES_FILE = Path(__file__).parent.parent / "backend" / "sz_lof_codes.json"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "lof_kline_data.json"
SAMPLE_SIZE = 10

def load_lof_codes():
    with open(LOF_CODES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.keys())

def main():
    from history_fetcher import fetch_kline_data, _make_session
    
    print("=" * 60)
    print("LOF基金日线数据导出工具")
    print("=" * 60)
    
    lof_codes = load_lof_codes()
    print(f"LOF基金总数: {len(lof_codes)}")
    
    end_date = datetime.now().strftime("%Y%m%d")
    beg_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    print(f"数据范围: {beg_date} ~ {end_date}")
    
    session = _make_session()
    
    # 第一步：样本校验
    print(f"\n--- 第一步：获取 {SAMPLE_SIZE} 个样本校验 ---")
    sample_codes = lof_codes[:SAMPLE_SIZE]
    sample_results = []
    
    for i, code in enumerate(sample_codes, 1):
        print(f"[{i}/{SAMPLE_SIZE}] 获取 {code}...", end=" ")
        try:
            data = fetch_kline_data(session, code, beg_date, end_date)
            count = len(data) if data else 0
            status = "success" if count > 0 else "no_data"
            sample_results.append({"code": code, "data": data or {}, "count": count, "status": status})
            print(f"{count} 条")
        except Exception as e:
            sample_results.append({"code": code, "data": {}, "count": 0, "status": "error"})
            print(f"ERROR: {str(e)[:30]}")
        time.sleep(0.3)
    
    # 校验样本
    print("\n=== 样本数据校验 ===")
    success_count = sum(1 for r in sample_results if r["status"] == "success")
    success_rate = success_count / len(sample_results) * 100
    print(f"成功率: {success_rate:.1f}% ({success_count}/{len(sample_results)})")
    
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
        try:
            data = fetch_kline_data(session, code, beg_date, end_date)
            count = len(data) if data else 0
            status = "success" if count > 0 else "no_data"
            all_results.append({"code": code, "data": data or {}, "count": count, "status": status})
            if count > 0:
                total_success += 1
                print(f"{count} 条")
            else:
                total_fail += 1
                print(f"NO DATA")
        except Exception as e:
            all_results.append({"code": code, "data": {}, "count": 0, "status": "error"})
            total_fail += 1
            print(f"ERROR")
        
        if i % 100 == 0:
            # 保存中间结果
            output = {
                "metadata": {
                    "fetch_time": datetime.now().isoformat(),
                    "date_range": {"start": beg_date, "end": end_date},
                    "total_funds": len(all_results),
                    "success_count": sum(1 for r in all_results if r["status"] == "success"),
                },
                "data": {r["code"]: r["data"] for r in all_results if r["status"] == "success"}
            }
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            print(f"  -> 已保存中间结果")
        
        time.sleep(0.3)
    
    elapsed = time.time() - start_time
    
    # 保存最终结果
    output = {
        "metadata": {
            "fetch_time": datetime.now().isoformat(),
            "date_range": {"start": beg_date, "end": end_date},
            "total_funds": len(all_results),
            "success_count": total_success,
        },
        "data": {r["code"]: r["data"] for r in all_results if r["status"] == "success"}
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
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
