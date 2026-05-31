#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上传剩余基金日线数据到阿里云PostgreSQL
"""
import json
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("请先安装psycopg2: pip install psycopg2-binary")
    sys.exit(1)

# 数据文件路径
DATA_FILE = Path(__file__).parent / "lof_kline_remaining.json"

# 阿里云数据库配置
DB_CONFIG = {
    "host": "101.200.129.61",
    "port": 5432,
    "database": "jinkuaicha",
    "user": "deploy",
    "password": "<REDACTED-PASSWORD>",
    "options": "-c statement_timeout=60000"
}

def load_data():
    """加载数据文件"""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def upload_data(conn, data):
    """上传数据"""
    cur = conn.cursor()
    total = 0
    
    for code, dates in data["data"].items():
        for date_str, kline_data in dates.items():
            price = kline_data.get("price")
            open_price = kline_data.get("open")
            high = kline_data.get("high")
            low = kline_data.get("low")
            volume = kline_data.get("volume")
            change_pct = kline_data.get("change_pct")
            source = kline_data.get("source", "tencent")
            
            cur.execute("""
                INSERT INTO daily_kline (code, trade_date, price, open, high, low, volume, change_pct, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                    price = EXCLUDED.price,
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    change_pct = EXCLUDED.change_pct,
                    source = EXCLUDED.source;
            """, (code, date_str, price, open_price, high, low, volume, change_pct, source))
            total += 1
            
            # 每1000条提交一次
            if total % 1000 == 0:
                conn.commit()
                print(f"已上传 {total} 条...")
    
    conn.commit()
    cur.close()
    return total

def main():
    print("=" * 60)
    print("上传剩余基金日线数据到阿里云PostgreSQL")
    print("=" * 60)
    
    # 加载数据
    data = load_data()
    print(f"数据文件: {DATA_FILE}")
    print(f"基金数量: {len(data['data'])}")
    
    # 连接数据库
    print(f"\n连接数据库: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("数据库连接成功")
    except Exception as e:
        print(f"数据库连接失败: {e}")
        return
    
    # 上传数据
    print("\n开始上传数据...")
    total = upload_data(conn, data)
    print(f"\n上传完成！共 {total} 条数据")
    
    # 验证
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM daily_kline;")
    count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT code) FROM daily_kline;")
    fund_count = cur.fetchone()[0]
    cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_kline;")
    date_range = cur.fetchone()
    cur.execute("SELECT source, COUNT(*) FROM daily_kline GROUP BY source;")
    sources = cur.fetchall()
    cur.close()
    
    print(f"\n数据库验证:")
    print(f"  总记录数: {count}")
    print(f"  基金数量: {fund_count}")
    print(f"  日期范围: {date_range[0]} ~ {date_range[1]}")
    print(f"  数据来源: {dict(sources)}")
    
    conn.close()

if __name__ == "__main__":
    main()
