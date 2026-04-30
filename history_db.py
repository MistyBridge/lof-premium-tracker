# -*- coding: utf-8 -*-
"""
LOF基金历史溢价率存储模块
使用 SQLite 存储每日溢价率快照，保留最近7天数据
用于计算三日平均溢价率等历史指标

三日平均溢价率计算规则：
  - 1天数据：直接使用当日溢价率
  - 2天数据：两天溢价率的成交量加权平均
  - 3天数据：三天溢价率的成交量加权平均
"""
import sqlite3
import logging
import threading
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 数据库文件路径（与 app.py 同目录）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lof_history.db")

# 保留天数
RETENTION_DAYS = 7


class HistoryDB:
    """线程安全的 SQLite 历史数据库"""

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程使用独立连接"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        """创建表结构"""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS premium_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                code TEXT NOT NULL,
                premium_rate REAL,
                price REAL,
                nav REAL,
                amount REAL DEFAULT 0,
                UNIQUE(date, code)
            );
            CREATE INDEX IF NOT EXISTS idx_snap_date ON premium_snapshots(date);
            CREATE INDEX IF NOT EXISTS idx_snap_code ON premium_snapshots(code);
            CREATE INDEX IF NOT EXISTS idx_snap_date_code ON premium_snapshots(date, code);
        """)
        # 兼容旧库：若缺少 amount 列则添加
        try:
            conn.execute("SELECT amount FROM premium_snapshots LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE premium_snapshots ADD COLUMN amount REAL DEFAULT 0")
            conn.commit()
            logger.info("Added 'amount' column to existing premium_snapshots table")
        conn.commit()
        logger.info(f"HistoryDB initialized: {self._db_path}")

    def save_snapshot(self, funds: Dict[str, dict]):
        """
        保存当前时刻的溢价率快照
        funds: { code: { "premium_rate": float, "price": float, "nav": float, "amount": float, ... }, ... }
        """
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_conn()

        # 使用 INSERT OR REPLACE 实现幂等：同一天多次刷新只保留最新
        rows = []
        for code, fund in funds.items():
            premium = fund.get("premium_rate")
            price = fund.get("price")
            nav = fund.get("nav")
            amount = fund.get("amount") or 0
            if premium is None:
                continue
            rows.append((today, code, premium, price, nav, amount))

        if not rows:
            return

        try:
            conn.executemany(
                "INSERT OR REPLACE INTO premium_snapshots (date, code, premium_rate, price, nav, amount) VALUES (?, ?, ?, ?, ?, ?)",
                rows
            )
            conn.commit()
            logger.info(f"Saved snapshot for {today}: {len(rows)} funds")
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")
            conn.rollback()

        # 清理过期数据
        self._cleanup()

    def _cleanup(self):
        """清理超过 RETENTION_DAYS 的历史数据"""
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM premium_snapshots WHERE date < ?", (cutoff,)
            )
            if cursor.rowcount > 0:
                conn.commit()
                logger.info(f"Cleaned up {cursor.rowcount} rows older than {cutoff}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            conn.rollback()

    def _calc_weighted_avg(self, entries: List[dict]) -> Optional[float]:
        """
        计算成交量加权平均溢价率
        - 1天数据：直接返回当日溢价率
        - 2天数据：两天的成交量加权平均
        - 3天数据：三天的成交量加权平均
        """
        if not entries:
            return None

        if len(entries) == 1:
            return round(entries[0]["premium_rate"], 3)

        # 成交量加权平均: sum(premium_rate * amount) / sum(amount)
        total_weighted = sum(e["premium_rate"] * (e["amount"] or 0) for e in entries)
        total_amount = sum(e["amount"] or 0 for e in entries)

        if total_amount == 0:
            # 无成交额数据时退化为简单算术平均
            return round(sum(e["premium_rate"] for e in entries) / len(entries), 3)

        return round(total_weighted / total_amount, 3)

    def get_avg_premium_3d(self, code: str) -> Optional[float]:
        """
        计算某只基金最近3天的平均溢价率（成交量加权）
        返回 None 如果没有历史数据
        """
        conn = self._get_conn()
        # 取最近3个不同日期的数据
        rows = conn.execute(
            """
            SELECT date, premium_rate, amount FROM premium_snapshots
            WHERE code = ? AND premium_rate IS NOT NULL
            ORDER BY date DESC LIMIT 3
            """,
            (code,)
        ).fetchall()

        return self._calc_weighted_avg([dict(r) for r in rows])

    def get_all_avg_premium_3d(self) -> Dict[str, Optional[float]]:
        """
        批量计算所有基金的三日平均溢价率（成交量加权）
        返回 { code: avg_premium_3d }
        """
        conn = self._get_conn()

        # 取最近3个日期
        dates_rows = conn.execute(
            "SELECT DISTINCT date FROM premium_snapshots ORDER BY date DESC LIMIT 3"
        ).fetchall()
        dates = [r["date"] for r in dates_rows]

        if not dates:
            return {}

        # 查询这些日期的所有数据（含 amount）
        placeholders = ",".join("?" * len(dates))
        rows = conn.execute(
            f"""
            SELECT code, date, premium_rate, amount
            FROM premium_snapshots
            WHERE date IN ({placeholders}) AND premium_rate IS NOT NULL
            """,
            dates
        ).fetchall()

        # 按基金代码分组，分别计算加权平均
        code_entries = defaultdict(list)
        for r in rows:
            code_entries[r["code"]].append(dict(r))

        result = {}
        for code, entries in code_entries.items():
            avg = self._calc_weighted_avg(entries)
            if avg is not None:
                result[code] = avg

        return result

    def get_history(self, code: str = None, days: int = 7) -> list:
        """
        获取历史数据
        code: 基金代码，None 表示全部
        days: 查询天数
        """
        conn = self._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        if code:
            rows = conn.execute(
                """
                SELECT date, code, premium_rate, price, nav, amount
                FROM premium_snapshots
                WHERE code = ? AND date >= ?
                ORDER BY date DESC
                """,
                (code, cutoff)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT date, code, premium_rate, price, nav, amount
                FROM premium_snapshots
                WHERE date >= ?
                ORDER BY date DESC
                """,
                (cutoff,)
            ).fetchall()

        return [dict(r) for r in rows]

    def get_available_dates(self) -> list:
        """获取有数据的日期列表"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT date FROM premium_snapshots ORDER BY date DESC LIMIT 7"
        ).fetchall()
        return [r["date"] for r in rows]


# ── Singleton ─────────────────────────────────────
_instance = None
_inst_lock = threading.Lock()


def get_history_db() -> HistoryDB:
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = HistoryDB()
    return _instance
