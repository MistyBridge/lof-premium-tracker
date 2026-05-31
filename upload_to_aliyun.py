#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上传日线数据到阿里云PostgreSQL数据库
"""
import json
import sys
from pathlib import Path
from datetime import datetime

# 数据文件路径
DATA_FILE = Path(__file__).parent / "data" / "lof_kline_data.json"

def load_data():
    """加载数据文件"""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def create_table_sql():
    """创建表的SQL语句"""
    return """
    CREATE TABLE IF NOT EXISTS daily_kline (
        code VARCHAR(6) NOT NULL,
        trade_date DATE NOT NULL,
        price NUMERIC(12, 4),
        open NUMERIC(12, 4),
        high NUMERIC(12, 4),
        low NUMERIC(12, 4),
        volume BIGINT,
        amount NUMERIC(16, 2),
        change_pct NUMERIC(10, 4),
        turnover_rate NUMERIC(10, 4),
        nav NUMERIC(12, 4),
        premium_rate NUMERIC(10, 4),
        source VARCHAR(20),
        created_at TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (code, trade_date)
    );
    
    CREATE INDEX IF NOT EXISTS idx_daily_code ON daily_kline (code);
    CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_kline (trade_date);
    """

def insert_data_sql(code, date_str, data):
    """生成插入数据的SQL"""
    price = data.get("price")
    open_price = data.get("open")
    high = data.get("high")
    low = data.get("low")
    volume = data.get("volume")
    source = data.get("source", "sina")
    
    return f"""
    INSERT INTO daily_kline (code, trade_date, price, open, high, low, volume, source)
    VALUES ('{code}', '{date_str}', {price}, {open_price}, {high}, {low}, {volume}, '{source}')
    ON CONFLICT (code, trade_date) DO UPDATE SET
        price = EXCLUDED.price,
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        volume = EXCLUDED.volume,
        source = EXCLUDED.source;
    """

def main():
    print("=" * 60)
    print("上传日线数据到阿里云PostgreSQL")
    print("=" * 60)
    
    # 加载数据
    data = load_data()
    print(f"数据文件: {DATA_FILE}")
    print(f"基金数量: {len(data['data'])}")
    
    # 生成SQL文件
    sql_file = Path(__file__).parent / "data" / "upload_kline.sql"
    with open(sql_file, "w", encoding="utf-8") as f:
        # 写入建表语句
        f.write("-- 创建表\n")
        f.write(create_table_sql())
        f.write("\n-- 插入数据\n")
        
        total_rows = 0
        for code, dates in data["data"].items():
            for date_str, kline_data in dates.items():
                f.write(insert_data_sql(code, date_str, kline_data))
                total_rows += 1
        
        f.write(f"\n-- 共 {total_rows} 条数据\n")
    
    print(f"SQL文件已生成: {sql_file}")
    print(f"总数据行数: {total_rows}")
    
    print("\n=== 上传步骤 ===")
    print("1. 将SQL文件上传到阿里云ECS:")
    print(f"   scp {sql_file} root@101.200.129.61:/tmp/")
    print("\n2. 在ECS上执行SQL:")
    print("   psql -U postgres -d lof_funds -f /tmp/upload_kline.sql")
    print("\n3. 或者使用Python脚本直接连接数据库上传")

if __name__ == "__main__":
    main()
