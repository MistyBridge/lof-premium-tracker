"""
数据库迁移 — 建表 + 索引 + 分区 + 物化视图 + 日历预置 + 校验
用法: python migration.py [check|status|seed|validate]
"""
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("migration")

# ── 表结构 SQL ──────────────────────────────────────────────

TABLES_SQL = [
    # 1. fund_info
    """CREATE TABLE IF NOT EXISTS fund_info (
        code               VARCHAR(6) PRIMARY KEY,
        name               VARCHAR(100) NOT NULL,
        fund_type          VARCHAR(20),
        index_code         VARCHAR(200),
        market             CHAR(2) NOT NULL,
        aum                NUMERIC(16,2),
        listing_date       DATE,
        redeem_days        INTEGER DEFAULT 2,
        qdii_quota_status  VARCHAR(20) DEFAULT 'open',
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 2. fund_daily
    """CREATE TABLE IF NOT EXISTS fund_daily (
        code               VARCHAR(6) NOT NULL,
        trade_date         DATE NOT NULL,
        open               NUMERIC(12,4),
        high               NUMERIC(12,4),
        low                NUMERIC(12,4),
        close              NUMERIC(12,4),
        volume             BIGINT,
        amount             NUMERIC(16,2),
        nav                NUMERIC(12,4),
        nav_date           DATE,
        nav_type           VARCHAR(20) DEFAULT 'confirmed',
        nav_source         VARCHAR(20),
        data_source        VARCHAR(20),
        float_share        NUMERIC(16,2),
        total_share        NUMERIC(16,2),
        premium_rate       NUMERIC(10,4),
        turnover_rate      NUMERIC(10,4),
        change_pct         NUMERIC(10,4),
        fetch_batch_id     VARCHAR(36),
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        updated_at         TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (code, trade_date)
    )""",
    # 3. fund_fee
    """CREATE TABLE IF NOT EXISTS fund_fee (
        code                VARCHAR(6) PRIMARY KEY,
        purchase_fee_rate   NUMERIC(10,4),
        redemption_fee_rate NUMERIC(10,4),
        purchase_limit      NUMERIC(16,2),
        purchase_status     VARCHAR(20),
        redeem_status       VARCHAR(20),
        fetched_at          TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 4. fund_holdings
    """CREATE TABLE IF NOT EXISTS fund_holdings (
        code               VARCHAR(6) PRIMARY KEY,
        quarter            VARCHAR(10),
        report_date        DATE,
        holdings           JSONB NOT NULL DEFAULT '[]',
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 5. fund_code_list
    """CREATE TABLE IF NOT EXISTS fund_code_list (
        code               VARCHAR(6) PRIMARY KEY,
        name               VARCHAR(100),
        market             CHAR(2) NOT NULL,
        last_seen          DATE NOT NULL,
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 5b. fund_category
    """CREATE TABLE IF NOT EXISTS fund_category (
        code               VARCHAR(6) NOT NULL,
        category           VARCHAR(20) NOT NULL,
        PRIMARY KEY (code, category)
    )""",
    # 6. asset_master
    """CREATE TABLE IF NOT EXISTS asset_master (
        code               VARCHAR(12) PRIMARY KEY,
        name               VARCHAR(100) NOT NULL,
        asset_type         VARCHAR(20),
        market             CHAR(2),
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 7. asset_daily (分区表父表)
    """CREATE TABLE IF NOT EXISTS asset_daily (
        code               VARCHAR(12) NOT NULL,
        trade_date         DATE NOT NULL,
        close              NUMERIC(12,4),
        change_pct         NUMERIC(10,4),
        volume             BIGINT,
        amount             NUMERIC(16,2),
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (code, trade_date)
    ) PARTITION BY RANGE (trade_date)""",
    # 8. fund_asset_map
    """CREATE TABLE IF NOT EXISTS fund_asset_map (
        fund_code          VARCHAR(6) NOT NULL,
        asset_code         VARCHAR(12) NOT NULL,
        report_date        DATE NOT NULL,
        weight             NUMERIC(8,4),
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (fund_code, asset_code, report_date)
    )""",
    # 9. trade_calendar
    """CREATE TABLE IF NOT EXISTS trade_calendar (
        trade_date         DATE PRIMARY KEY,
        is_trading         BOOLEAN NOT NULL DEFAULT TRUE
    )""",
    # 10. fetch_progress
    """CREATE TABLE IF NOT EXISTS fetch_progress (
        task_name          VARCHAR(50) PRIMARY KEY,
        last_code          VARCHAR(12),
        completed          INTEGER DEFAULT 0,
        total              INTEGER DEFAULT 0,
        failed_codes       JSONB DEFAULT '[]',
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 11. job_log
    """CREATE TABLE IF NOT EXISTS job_log (
        id                 SERIAL PRIMARY KEY,
        job_name           VARCHAR(50) NOT NULL,
        status             VARCHAR(20) NOT NULL,
        duration_ms        INTEGER,
        detail             TEXT,
        started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        finished_at        TIMESTAMPTZ
    )""",
    # 12. admin_audit_log
    """CREATE TABLE IF NOT EXISTS admin_audit_log (
        id                 SERIAL PRIMARY KEY,
        user_id            VARCHAR(64) NOT NULL,
        action             VARCHAR(100) NOT NULL,
        target             VARCHAR(200),
        detail             TEXT,
        created_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 13. user_formula_group
    """CREATE TABLE IF NOT EXISTS user_formula_group (
        id                 SERIAL PRIMARY KEY,
        user_id            VARCHAR(64) NOT NULL,
        name               VARCHAR(100) NOT NULL,
        description        VARCHAR(500),
        sort_order         INTEGER DEFAULT 0,
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 14. user_formula
    """CREATE TABLE IF NOT EXISTS user_formula (
        id                 SERIAL PRIMARY KEY,
        user_id            VARCHAR(64) NOT NULL,
        group_id           INTEGER REFERENCES user_formula_group(id) ON DELETE SET NULL,
        name               VARCHAR(100) NOT NULL,
        expression         TEXT NOT NULL,
        description        VARCHAR(500),
        sort_order         INTEGER DEFAULT 0,
        version            INTEGER DEFAULT 1,
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 15. user_watchlist
    """CREATE TABLE IF NOT EXISTS user_watchlist (
        user_id            VARCHAR(64) NOT NULL,
        fund_code          VARCHAR(6) NOT NULL,
        sort_order         INTEGER DEFAULT 0,
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (user_id, fund_code)
    )""",
    # 16. user_alert
    """CREATE TABLE IF NOT EXISTS user_alert (
        id                 SERIAL PRIMARY KEY,
        user_id            VARCHAR(64) NOT NULL,
        name               VARCHAR(100) NOT NULL,
        fund_code          VARCHAR(6),
        condition          JSONB NOT NULL,
        is_active          BOOLEAN DEFAULT TRUE,
        email              VARCHAR(255),
        last_triggered_at  TIMESTAMPTZ,
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        updated_at         TIMESTAMPTZ DEFAULT NOW()
    )""",
    # 17. fund_est_nav
    """CREATE TABLE IF NOT EXISTS fund_est_nav (
        code               VARCHAR(6) NOT NULL,
        trade_date         DATE NOT NULL,
        est_nav            NUMERIC(12,4),
        est_change_pct     NUMERIC(10,4),
        holdings_contrib   NUMERIC(10,4),
        index_contrib      NUMERIC(10,4),
        coverage           NUMERIC(10,4),
        nav                NUMERIC(12,4),
        created_at         TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (code, trade_date)
    )""",
]

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_daily_code_date ON fund_daily (code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_daily_date ON fund_daily (trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_holdings_code ON fund_holdings (code)",
    "CREATE INDEX IF NOT EXISTS idx_fam_fund ON fund_asset_map (fund_code)",
    "CREATE INDEX IF NOT EXISTS idx_fam_asset ON fund_asset_map (asset_code)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_active ON user_alert (user_id) WHERE is_active = TRUE",
    "CREATE INDEX IF NOT EXISTS idx_job_name ON job_log (job_name, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_est_nav_date ON fund_est_nav (trade_date DESC)",
]

# 列迁移（ALTER TABLE ADD COLUMN IF NOT EXISTS，兼容已有表）
ALTER_TABLE_SQL = [
    "ALTER TABLE user_alert ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
]

# 列加宽迁移: (表, 列, 目标长度)。
#
# 为什么不能直接放进 ALTER_TABLE_SQL 无条件执行：
# PostgreSQL 不允许 ALTER 一个被物化视图引用的列（报
# "cannot alter type of a column used by a view or rule"），
# 所以必须先把 fund_snapshot 摘掉、改完列、再重建视图。
# 这里只在"当前长度确实不足"时才改动，因此可以安全地重复执行。
#
# index_code 存的是"跟踪标的"名称而非指数代码（见 fetchers/info.py 的
# _parse_info 取 <th>跟踪标的</th>），原 VARCHAR(20) 装不下 QDII 类的
# 长指数名，导致这些基金整批写入失败、永远进不了 fund_info：
#   'S&P Oil & Gas Exploration & Production Select Industry'  (54 字符)
#   '中债-7-10年政策性金融债全价(总值)指数'                      (22 字符)
COLUMN_WIDEN_SQL = [
    ("fund_info", "index_code", 200),
]

# 物化视图定义版本。任何一次改动 MATERIALIZED_VIEW_SQL 都必须递增此值，
# 否则已有库不会重建（CREATE MATERIALIZED VIEW IF NOT EXISTS 对已存在的
# 视图是空操作），定义改动就会静默失效。
#
# v2: 补回 float_share / suspension_status / is_suspended / aum /
#     purchase_status / category 六列。v1 用的是基线定义，重建时把这六列
#     丢了，导致 API 的 filter=lof/etf（`WHERE category = 'LOF'`）直接
#     报 UndefinedColumn，前端基金列表整页加载失败。
MV_VERSION = 2

# fund_snapshot 的索引。原先只存在于手工执行的
# sql/migrations/003_optimize_performance.sql 里，一旦视图被重建
# （例如上面的列加宽必须先摘视图）这些索引就会全部丢失，其中
# idx_snapshot_code 是 REFRESH ... CONCURRENTLY 的硬性前置条件，
# 丢了会让每日刷新静默失败。因此定义必须跟着视图走。
#
# 这里刻意不用 CONCURRENTLY：整个重建放在一个事务里做才安全（否则
# 中间会出现 fund_snapshot 不存在的窗口，API 直接报错）。MV 只有
# 2000 行出头，非并发建索引的锁表时间是毫秒级。
MV_INDEXES_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_code ON fund_snapshot (code)",
    "CREATE INDEX IF NOT EXISTS idx_snap_amount ON fund_snapshot (amount DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_premium ON fund_snapshot (premium_rate DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_change ON fund_snapshot (change_pct DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_turnover ON fund_snapshot (turnover_rate DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_volume ON fund_snapshot (volume DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_close ON fund_snapshot (close DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_nav ON fund_snapshot (nav DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_type_amount ON fund_snapshot (fund_type, amount DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS idx_snap_type_premium ON fund_snapshot (fund_type, premium_rate DESC NULLS LAST)",
]

# 迁移元数据表：记录已应用的 MV 定义版本等信息
SCHEMA_META_SQL = """CREATE TABLE IF NOT EXISTS schema_meta (
    key        VARCHAR(64) PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
)"""

MATERIALIZED_VIEW_SQL = """CREATE MATERIALIZED VIEW IF NOT EXISTS fund_snapshot AS
SELECT
    fi.code,
    fi.name,
    fi.fund_type,
    fi.market,
    fd.trade_date,
    fd.close,
    fd.nav,
    fd.premium_rate,
    fd.turnover_rate,
    fd.change_pct,
    fd.amount,
    fd.volume,
    fd.float_share,
    fd.suspension_status,
    COALESCE(fd.suspension_status = 'suspended', FALSE) AS is_suspended,
    fi.aum,
    -- purchase_status / category 用标量子查询而不是 JOIN：
    -- 保证每个 code 恰好取到一个值，避免行数膨胀破坏 idx_snapshot_code 唯一索引。
    (SELECT ff.purchase_status FROM fund_fee ff
      WHERE ff.code = fi.code LIMIT 1) AS purchase_status,
    -- 一个 code 可能同时挂在多个类别下，而 API 的 filter=lof/etf 需要单一值。
    -- 按固定优先级取第一个，保证每次刷新的结果稳定可复现。
    COALESCE((
        SELECT fc.category FROM fund_category fc
        WHERE fc.code = fi.code
        ORDER BY CASE fc.category
                   WHEN 'ETF' THEN 1 WHEN 'LOF' THEN 2 WHEN 'REITs' THEN 3
                   ELSE 4 END, fc.category
        LIMIT 1), '') AS category
FROM fund_info fi
LEFT JOIN LATERAL (
    SELECT * FROM fund_daily
    WHERE code = fi.code
      AND close IS NOT NULL
    ORDER BY trade_date DESC LIMIT 1
) fd ON TRUE"""

EXPECTED_TABLES = [
    "fund_info", "fund_daily", "fund_fee", "fund_holdings", "fund_code_list",
    "fund_category",
    "asset_master", "asset_daily", "fund_asset_map", "trade_calendar",
    "fetch_progress", "job_log", "admin_audit_log",
    "user_formula_group", "user_formula", "user_watchlist", "user_alert",
    "fund_est_nav", "schema_meta",
]


# ── 分区管理 ────────────────────────────────────────────────


async def ensure_partition(conn: asyncpg.Connection, target_date: date) -> None:
    """确保 asset_daily 目标月份分区存在"""
    table = "asset_daily"
    suffix = target_date.strftime("%Y%m")
    partition_name = f"{table}_{suffix}"
    start_date = target_date.replace(day=1)
    if start_date.month == 12:
        end_date = start_date.replace(year=start_date.year + 1, month=1)
    else:
        end_date = start_date.replace(month=start_date.month + 1)

    exists = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE tablename = $1)",
        partition_name,
    )
    if not exists:
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {partition_name} "
            f"PARTITION OF {table} "
            f"FOR VALUES FROM ('{start_date}') TO ('{end_date}')"
        )
        logger.info("分区创建: %s", partition_name)


# ── 核心迁移 ────────────────────────────────────────────────


async def _column_length(conn: asyncpg.Connection, table: str,
                         column: str) -> int | None:
    """列的字符长度上限；非字符串列返回 None。"""
    return await conn.fetchval(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = $1 AND column_name = $2", table, column)


async def _mv_exists(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        "SELECT to_regclass('public.fund_snapshot') IS NOT NULL"))


async def _mv_version_ok(conn: asyncpg.Connection) -> bool:
    """物化视图定义是否已是当前版本。"""
    value = await conn.fetchval(
        "SELECT value FROM schema_meta WHERE key = 'mv_fund_snapshot_version'")
    return value == str(MV_VERSION)


async def _sync_materialized_view(conn: asyncpg.Connection) -> None:
    """按需重建 fund_snapshot 并确保索引齐备。

    重建的触发条件（任一成立）：
      * 视图不存在；
      * schema_meta 里记录的 MV_VERSION 与代码中的不一致（定义改过）；
      * 有列加宽待执行 —— PG 不允许 ALTER 被视图引用的列，必须先摘视图。

    整个"摘视图 → 改列 → 建视图 → 建索引"放在同一个事务里，
    避免中间出现 fund_snapshot 不存在的窗口把 API 打挂。
    """
    pending = []
    for table, column, width in COLUMN_WIDEN_SQL:
        current = await _column_length(conn, table, column)
        if current is not None and current < width:
            pending.append((table, column, current, width))

    exists = await _mv_exists(conn)
    version_ok = await _mv_version_ok(conn) if exists else False
    if version_ok and not pending:
        # 视图已是最新定义，但仍要补齐可能缺失的索引
        for sql in MV_INDEXES_SQL:
            await conn.execute(sql)
        logger.info("物化视图 fund_snapshot 已是最新定义，跳过重建")
        return

    reason = []
    if pending:
        reason.append(f"待加宽列 {len(pending)} 个")
    if exists and not version_ok:
        reason.append("视图定义版本过期")
    if not exists:
        reason.append("视图不存在")

    async with conn.transaction():
        if exists:
            await conn.execute("DROP MATERIALIZED VIEW fund_snapshot")
        for table, column, current, width in pending:
            await conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"TYPE VARCHAR({width})")
            logger.info("列加宽: %s.%s VARCHAR(%d) -> VARCHAR(%d)",
                        table, column, current, width)
        await conn.execute(MATERIALIZED_VIEW_SQL)
        for sql in MV_INDEXES_SQL:
            await conn.execute(sql)
        await conn.execute(
            "INSERT INTO schema_meta (key, value, updated_at) "
            "VALUES ('mv_fund_snapshot_version', $1, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
            "updated_at = NOW()", str(MV_VERSION))
    logger.info("物化视图 fund_snapshot 已重建（%s）", "；".join(reason))


async def run_migration(conn: asyncpg.Connection) -> None:
    """执行全部迁移"""
    logger.info("=== 开始数据库迁移 ===")

    # 1. 建表
    for sql in TABLES_SQL:
        await conn.execute(sql)
    await conn.execute(SCHEMA_META_SQL)
    logger.info("%d 张表创建完成", len(TABLES_SQL) + 1)

    # 1.1 列迁移（ALTER TABLE ADD COLUMN IF NOT EXISTS）
    for sql in ALTER_TABLE_SQL:
        await conn.execute(sql)
    logger.info("列迁移完成")

    # 2. 建索引
    for sql in INDEXES_SQL:
        await conn.execute(sql)
    logger.info("索引创建完成")

    # 3. 分区（当月+下月）
    today = date.today()
    await ensure_partition(conn, today)
    next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    await ensure_partition(conn, next_month)
    logger.info("分区（当月+下月）就绪")

    # 4. 物化视图（含必须在摘视图后才能执行的列加宽）
    await _sync_materialized_view(conn)

    logger.info("=== 迁移完成 ===")


async def seed_calendar(conn: asyncpg.Connection) -> None:
    """插入交易日历预置数据（2025-2026 年）"""
    count = await conn.fetchval("SELECT count(*) FROM trade_calendar")
    if count > 0:
        logger.info("交易日历已有 %d 条数据，跳过 seed", count)
        return

    # 生成 2025-2026 所有日期
    holidays = _get_holidays()
    rows = []
    d = date(2025, 1, 1)
    end = date(2026, 12, 31)
    while d <= end:
        is_trading = d.weekday() < 5 and d not in holidays
        rows.append((d, is_trading))
        d += timedelta(days=1)

    await conn.copy_records_to_table(
        "trade_calendar",
        records=rows,
        columns=["trade_date", "is_trading"],
    )
    trading = sum(1 for _, t in rows if t)
    logger.info("交易日历 seed 完成: %d 天，其中 %d 个交易日", len(rows), trading)


def _get_holidays() -> set[date]:
    """2025-2026 中国股市法定假日（休市日）"""
    h = set()

    # ── 2025 ──
    # 元旦: 1月1日
    h.add(date(2025, 1, 1))
    # 春节: 1月28日-2月4日 (8天)
    for d in range(28, 32):
        h.add(date(2025, 1, d))
    for d in range(1, 5):
        h.add(date(2025, 2, d))
    # 清明: 4月4日-6日
    for d in range(4, 7):
        h.add(date(2025, 4, d))
    # 五一: 5月1日-5日
    for d in range(1, 6):
        h.add(date(2025, 5, d))
    # 端午: 5月31日-6月2日
    h.add(date(2025, 5, 31))
    h.add(date(2025, 6, 1))
    h.add(date(2025, 6, 2))
    # 中秋+国庆: 10月1日-8日
    for d in range(1, 9):
        h.add(date(2025, 10, d))

    # ── 2026 ──
    # 元旦: 1月1日-3日
    for d in range(1, 4):
        h.add(date(2026, 1, d))
    # 春节: 2月17日-23日 (7天)
    for d in range(17, 24):
        h.add(date(2026, 2, d))
    # 清明: 4月5日-7日
    for d in range(5, 8):
        h.add(date(2026, 4, d))
    # 五一: 5月1日-5日
    for d in range(1, 6):
        h.add(date(2026, 5, d))
    # 端午: 6月19日-21日
    for d in range(19, 22):
        h.add(date(2026, 6, d))
    # 中秋: 9月25日-27日
    for d in range(25, 28):
        h.add(date(2026, 9, d))
    # 国庆: 10月1日-7日
    for d in range(1, 8):
        h.add(date(2026, 10, d))

    return h


# ── 校验 ────────────────────────────────────────────────────


async def validate(conn: asyncpg.Connection) -> None:
    """校验表结构完整性"""
    logger.info("=== 校验表结构 ===")

    # 检查 16 张表是否存在
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing = {r["tablename"] for r in tables}
    missing = [t for t in EXPECTED_TABLES if t not in existing]
    if missing:
        logger.error("缺失表: %s", ", ".join(missing))
    else:
        logger.info("%d 张表全部存在 ✓", len(EXPECTED_TABLES))

    # 检查交易日历
    year = date.today().year
    count = await conn.fetchval(
        "SELECT count(*) FROM trade_calendar "
        "WHERE is_trading = TRUE AND EXTRACT(year FROM trade_date) = $1",
        year,
    )
    if count == 0:
        logger.warning("当年交易日历为空，请执行 seed")
    elif 200 <= count <= 260:
        logger.info("交易日历校验通过: %d 年 %d 个交易日 ✓", year, count)
    else:
        logger.error("交易日历异常: %d 年只有 %d 个交易日，预期 200~260", year, count)

    # 检查分区
    partitions = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE tablename LIKE 'asset_daily_%'"
    )
    logger.info("asset_daily 分区: %d 个", len(partitions))

    # 检查物化视图
    mv = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_matviews WHERE matviewname = 'fund_snapshot')"
    )
    logger.info("物化视图 fund_snapshot: %s", "存在 ✓" if mv else "不存在 ✗")


async def check_pending(conn: asyncpg.Connection) -> None:
    """检查是否有待执行的迁移"""
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing = {r["tablename"] for r in tables}
    missing = [t for t in EXPECTED_TABLES if t not in existing]
    if missing:
        logger.info("待执行: 缺失 %d 张表 (%s)", len(missing), ", ".join(missing))
    else:
        logger.info("所有表已就绪，无待执行迁移")


async def show_status(conn: asyncpg.Connection) -> None:
    """显示当前数据库状态"""
    logger.info("=== 数据库状态 ===")
    for table in EXPECTED_TABLES:
        try:
            count = await conn.fetchval(f"SELECT count(*) FROM {table}")
            logger.info("  %-25s %d rows", table, count)
        except Exception:
            logger.info("  %-25s 不存在", table)


# ── CLI 入口 ────────────────────────────────────────────────


async def _get_conn() -> asyncpg.Connection:
    """获取数据库连接（从 .env 读取 DATABASE_URL）"""
    from dotenv import load_dotenv
    import os

    load_dotenv()
    url = os.getenv("DATABASE_URL", "")
    if not url:
        logger.error("DATABASE_URL 未设置")
        sys.exit(1)
    # asyncpg 只接受 postgresql:// 格式
    conn_url = url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(conn_url)


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    conn = await _get_conn()
    try:
        if cmd == "run":
            await run_migration(conn)
            await seed_calendar(conn)
            await validate(conn)
        elif cmd == "check":
            await check_pending(conn)
        elif cmd == "status":
            await show_status(conn)
        elif cmd == "seed":
            await seed_calendar(conn)
        elif cmd == "validate":
            await validate(conn)
        else:
            logger.error("未知命令: %s (可选: run|check|status|seed|validate)", cmd)
            sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
