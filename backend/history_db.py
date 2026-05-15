# -*- coding: utf-8 -*-
"""
LOF基金历史溢价率存储模块
使用 PostgreSQL 存储每日溢价率快照，保留最近21天数据
用于计算三日平均溢价率等历史指标

Schema:
  funds(code PK, name, created_at, updated_at)
  premium_snapshots(date, code PK, premium_rate, price, nav, amount, created_at)
    FK: code → funds(code) ON DELETE CASCADE

三日平均溢价率计算规则：
  - 1天数据：直接使用当日溢价率
  - 2天数据：两天溢价率的成交量加权平均
  - 3天数据：三天溢价率的成交量加权平均
"""
import logging
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras

from config import Config

logger = logging.getLogger(__name__)

# 保留天数
RETENTION_DAYS = 21
KLIN_RETENTION_DAYS = 395  # 365个交易日 + 30天缓冲


class HistoryDB:
    """线程安全的 PostgreSQL 历史数据库（连接池）"""

    def __init__(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=Config.DB_POOL_MIN,
            maxconn=Config.DB_POOL_MAX,
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            connect_timeout=10,
        )
        self._init_db()
        logger.info(
            "HistoryDB initialized: PostgreSQL %s:%s/%s (pool %d-%d)",
            Config.DB_HOST, Config.DB_PORT, Config.DB_NAME,
            Config.DB_POOL_MIN, Config.DB_POOL_MAX,
        )

    # ── Schema Management ────────────────────────────

    def _init_db(self):
        """初始化数据库：检测旧 schema 并自动迁移"""
        conn = self._pool.getconn()
        try:
            cur = conn.cursor()
            is_old = self._detect_old_schema(cur)
            if is_old:
                logger.info("Detected old schema (id column), migrating...")
                self._migrate_schema(cur)
                conn.commit()
                logger.info("Schema migration complete")
            else:
                self._ensure_new_schema(cur)
                conn.commit()
                logger.info("Schema up-to-date")
        except Exception as e:
            conn.rollback()
            logger.error("Failed to initialize database: %s", e)
            raise
        finally:
            self._pool.putconn(conn)

    def _detect_old_schema(self, cur) -> bool:
        """检测是否存在旧 schema（有 id 列）"""
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'premium_snapshots'
                  AND column_name = 'id'
            )
        """)
        return cur.fetchone()[0]

    def _ensure_new_schema(self, cur):
        """创建新 schema（幂等）"""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funds (
                code       VARCHAR(6) PRIMARY KEY,
                name       VARCHAR(100) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS premium_snapshots (
                date         DATE         NOT NULL,
                code         VARCHAR(6)   NOT NULL
                             REFERENCES funds(code) ON DELETE CASCADE,
                premium_rate NUMERIC(10,4),
                price        NUMERIC(12,4),
                nav          NUMERIC(12,4),
                amount       NUMERIC(16,2) DEFAULT 0,
                created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                PRIMARY KEY (date, code)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_snap_code_date
                ON premium_snapshots (code, date DESC)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_kline (
                date         DATE         NOT NULL,
                code         VARCHAR(6)   NOT NULL
                             REFERENCES funds(code) ON DELETE CASCADE,
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

    def _migrate_schema(self, cur):
        """从旧 schema 迁移到新 schema（事务内执行）"""
        # 1. 创建 funds 表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS funds (
                code       VARCHAR(6) PRIMARY KEY,
                name       VARCHAR(100) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            )
        """)
        # 2. 从旧表提取基金名称
        cur.execute("""
            INSERT INTO funds (code, name)
            SELECT DISTINCT code, MAX(name)
            FROM premium_snapshots
            WHERE name IS NOT NULL AND name != ''
            GROUP BY code
            ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name, updated_at = NOW()
        """)
        logger.info("Migrated %d fund names", cur.rowcount)

        # 3. 创建新表
        cur.execute("""
            CREATE TABLE premium_snapshots_v2 (
                date         DATE         NOT NULL,
                code         VARCHAR(6)   NOT NULL
                             REFERENCES funds(code) ON DELETE CASCADE,
                premium_rate NUMERIC(10,4),
                price        NUMERIC(12,4),
                nav          NUMERIC(12,4),
                amount       NUMERIC(16,2) DEFAULT 0,
                created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                PRIMARY KEY (date, code)
            )
        """)
        # 4. 迁移数据
        cur.execute("""
            INSERT INTO premium_snapshots_v2
                (date, code, premium_rate, price, nav, amount)
            SELECT
                date,
                code,
                premium_rate::NUMERIC(10,4),
                price::NUMERIC(12,4),
                nav::NUMERIC(12,4),
                COALESCE(amount, 0)::NUMERIC(16,2)
            FROM premium_snapshots
            WHERE premium_rate IS NOT NULL
            ON CONFLICT (date, code) DO UPDATE SET
                premium_rate = EXCLUDED.premium_rate,
                price        = EXCLUDED.price,
                nav          = EXCLUDED.nav,
                amount       = EXCLUDED.amount,
                created_at   = NOW()
        """)
        row_count = cur.rowcount
        # 5. 替换旧表
        cur.execute("DROP TABLE premium_snapshots")
        cur.execute("ALTER TABLE premium_snapshots_v2 RENAME TO premium_snapshots")
        # 6. 创建索引
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_snap_code_date
                ON premium_snapshots (code, date DESC)
        """)
        logger.info("Migrated %d snapshot rows", row_count)

    # ── Public API ───────────────────────────────────

    def save_snapshot(self, funds: Dict[str, dict], date: str = None):
        """
        保存溢价率快照（幂等：同日同基金覆盖写入）
        funds: { code: { premium_rate, price, nav, amount, name, ... }, ... }
        date: 保存日期，默认为今天
        """
        snapshot_date = date or datetime.now().strftime("%Y-%m-%d")
        fund_rows = []
        snap_rows = []
        for code, fund in funds.items():
            premium = fund.get("premium_rate")
            price = fund.get("price")
            nav = fund.get("nav")
            amount = fund.get("amount") or 0
            name = fund.get("name", "")
            if premium is None:
                continue
            fund_rows.append((code, name))
            snap_rows.append((snapshot_date, code, premium, price, nav, amount))

        if not snap_rows:
            return

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                # 事务内：先 upsert 基金名称，再 upsert 快照
                if fund_rows:
                    psycopg2.extras.execute_values(
                        cur,
                        """
                        INSERT INTO funds (code, name) VALUES %s
                        ON CONFLICT (code) DO UPDATE
                            SET name = EXCLUDED.name, updated_at = NOW()
                        """,
                        fund_rows,
                        page_size=500,
                    )
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO premium_snapshots
                        (date, code, premium_rate, price, nav, amount)
                    VALUES %s
                    ON CONFLICT (date, code) DO UPDATE SET
                        premium_rate = EXCLUDED.premium_rate,
                        price        = EXCLUDED.price,
                        nav          = EXCLUDED.nav,
                        amount       = EXCLUDED.amount,
                        created_at   = NOW()
                    """,
                    snap_rows,
                    page_size=500,
                )
            conn.commit()
            logger.info("Saved snapshot for %s: %d funds", snapshot_date, len(snap_rows))
        except Exception as e:
            logger.error("Failed to save snapshot: %s", e)
            conn.rollback()
        finally:
            self._pool.putconn(conn)

        self._cleanup()

    def get_snapshot_by_date(self, date: str) -> List[dict]:
        """获取某一天的所有快照数据（含基金名称，用于缓存初始化）"""
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT s.date::TEXT AS date, s.code, s.premium_rate,
                           s.price, s.nav, s.amount,
                           COALESCE(f.name, s.code) AS name
                    FROM premium_snapshots s
                    LEFT JOIN funds f ON s.code = f.code
                    WHERE s.date = %s AND s.premium_rate IS NOT NULL
                    """,
                    (date,)
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def get_avg_premium_3d(self, code: str) -> Optional[float]:
        """
        计算某只基金最近3天的平均溢价率（成交量加权）
        返回 None 如果没有历史数据
        """
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT date, premium_rate, amount FROM premium_snapshots
                    WHERE code = %s AND premium_rate IS NOT NULL
                    ORDER BY date DESC LIMIT 3
                    """,
                    (code,)
                )
                rows = cur.fetchall()
        finally:
            self._pool.putconn(conn)

        return self._calc_weighted_avg([dict(r) for r in rows])

    def get_all_avg_premium_3d(self) -> Dict[str, Optional[float]]:
        """
        批量计算所有基金的三日平均溢价率（成交量加权）
        返回 { code: avg_premium_3d }
        """
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT DISTINCT date FROM premium_snapshots ORDER BY date DESC LIMIT 3"
                )
                dates = [r["date"] for r in cur.fetchall()]

            if not dates:
                return {}

            placeholders = ",".join(["%s"] * len(dates))
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT code, date, premium_rate, amount
                    FROM premium_snapshots
                    WHERE date IN ({placeholders}) AND premium_rate IS NOT NULL
                    """,
                    dates
                )
                rows = cur.fetchall()
        finally:
            self._pool.putconn(conn)

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
        获取历史数据（含基金名称）
        code: 基金代码，None 表示全部
        days: 查询天数
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if code:
                    cur.execute(
                        """
                        SELECT s.date::TEXT AS date, s.code, s.premium_rate,
                               s.price, s.nav, s.amount,
                               COALESCE(f.name, s.code) AS name
                        FROM premium_snapshots s
                        LEFT JOIN funds f ON s.code = f.code
                        WHERE s.code = %s AND s.date >= %s
                        ORDER BY s.date DESC
                        """,
                        (code, cutoff)
                    )
                else:
                    cur.execute(
                        """
                        SELECT s.date::TEXT AS date, s.code, s.premium_rate,
                               s.price, s.nav, s.amount,
                               COALESCE(f.name, s.code) AS name
                        FROM premium_snapshots s
                        LEFT JOIN funds f ON s.code = f.code
                        WHERE s.date >= %s
                        ORDER BY s.date DESC
                        """,
                        (cutoff,)
                    )
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def get_available_dates(self) -> list:
        """获取有数据的日期列表"""
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT DISTINCT date::TEXT AS date FROM premium_snapshots ORDER BY date DESC LIMIT 7"
                )
                return [r["date"] for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    # ── Internal Helpers ─────────────────────────────

    def _cleanup(self):
        """清理超过 RETENTION_DAYS 的历史数据"""
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM premium_snapshots WHERE date < %s", (cutoff,)
                )
                if cur.rowcount > 0:
                    conn.commit()
                    logger.info("Cleaned up %d rows older than %s", cur.rowcount, cutoff)
        except Exception as e:
            logger.error("Cleanup failed: %s", e)
            conn.rollback()
        finally:
            self._pool.putconn(conn)

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
            return round(float(entries[0]["premium_rate"]), 3)

        total_weighted = sum(
            float(e["premium_rate"]) * (float(e["amount"] or 0))
            for e in entries
        )
        total_amount = sum(float(e["amount"] or 0) for e in entries)

        if total_amount == 0:
            return round(sum(float(e["premium_rate"]) for e in entries) / len(entries), 3)

        return round(total_weighted / total_amount, 3)

    # ── Daily K-line Methods ────────────────────────

    def save_kline_batch(self, rows: List[tuple]):
        """
        批量 upsert 日K线数据
        rows: [(date, code, price, nav, amount, change_pct, premium_rate), ...]
        """
        if not rows:
            return
        conn = self._pool.getconn()
        try:
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
                    page_size=500,
                )
            conn.commit()
            logger.info("Saved %d kline rows", len(rows))
        except Exception as e:
            logger.error("Failed to save kline batch: %s", e)
            conn.rollback()
        finally:
            self._pool.putconn(conn)
        self._cleanup_kline()

    def get_kline_history(self, code: str, days: int = 365) -> list:
        """
        获取基金日K线历史数据（按日期升序），无数据时回退到 premium_snapshots
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT date::TEXT AS date, price, nav, amount,
                           change_pct, premium_rate
                    FROM daily_kline
                    WHERE code = %s AND date >= %s
                    ORDER BY date ASC
                    """,
                    (code, cutoff)
                )
                rows = [dict(r) for r in cur.fetchall()]
                if rows:
                    return rows
                # 回退到 premium_snapshots（尚未拉取K线数据的基金）
                cur.execute(
                    """
                    SELECT date::TEXT AS date, price, nav, amount,
                           premium_rate
                    FROM premium_snapshots
                    WHERE code = %s AND date >= %s
                    ORDER BY date ASC
                    """,
                    (code, cutoff)
                )
                return [dict(r) for r in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def _cleanup_kline(self):
        """清理超过 KLIN_RETENTION_DAYS 的K线数据"""
        cutoff = (datetime.now() - timedelta(days=KLIN_RETENTION_DAYS)).strftime("%Y-%m-%d")
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM daily_kline WHERE date < %s", (cutoff,)
                )
                if cur.rowcount > 0:
                    conn.commit()
                    logger.info("Cleaned up %d kline rows older than %s", cur.rowcount, cutoff)
        except Exception as e:
            logger.error("Kline cleanup failed: %s", e)
            conn.rollback()
        finally:
            self._pool.putconn(conn)


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
