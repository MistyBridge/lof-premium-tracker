#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接连接阿里云PostgreSQL上传数据
需要在阿里云ECS上运行，或者本地有数据库连接
"""
import json
import sys
from pathlib import Path
from datetime import datetime

try:
    import psycopg2
except ImportError:
    print("请先安装psycopg2: pip install psycopg2-binary")
    sys.exit(1)

# 数据文件路径
DATA_FILE = Path(__file__).parent / "lof_kline_data.json"

# 数据库配置（需要修改为实际配置）
DB_CONFIG = {
    "host": "localhost",  # 或阿里云ECS的内网IP
    "port": 5432,
    "database": "lof_funds",
    "user": "postgres",
    "password": "your_password"  # 需要修改为实际密码
}

def load_data():
    """加载数据文件"""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def create_table(conn):
    """创建表"""
    cur = conn.cursor()
    cur.execute("""
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
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_code ON daily_kline (code);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_kline (trade_date);")
    conn.commit()
    cur.close()
    print("表创建成功")

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
            source = kline_data.get("source", "sina")
            
            cur.execute("""
                INSERT INTO daily_kline (code, trade_date, price, open, high, low, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                    price = EXCLUDED.price,
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    source = EXCLUDED.source;
            """, (code, date_str, price, open_price, high, low, volume, source))
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
    print("直接上传日线数据到PostgreSQL")
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
        print("\n请检查:")
        print("1. 数据库是否已创建")
        print("2. 连接配置是否正确")
        print("3. 防火墙是否开放5432端口")
        return
    
    # 创建表
    create_table(conn)
    
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
    cur.close()
    
    print(f"\n数据库验证:")
    print(f"  总记录数: {count}")
    print(f"  基金数量: {fund_count}")
    
    conn.close()

if __name__ == "__main__":
    main()
