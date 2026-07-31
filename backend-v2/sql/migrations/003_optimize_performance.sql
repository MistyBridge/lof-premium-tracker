-- ============================================================
-- 性能优化迁移 (003) — 金快查 backend-v2
-- 目标: 解决 fund_snapshot 列表/详情查询慢、并发响应长的问题
--
-- ⚠️ 执行说明:
--   1. 本文件每条语句单独 autocommit 执行（不要用 BEGIN 包裹）。
--   2. 带 CONCURRENTLY 的索引不阻塞读写，但本身不能在事务内运行。
--   3. 生产环境建议在低峰期执行，执行前先备份。
--   4. idx_snapshot_code 是唯一索引，REFRESH MATERIALIZED VIEW
--      CONCURRENTLY 的硬性前置条件（当前 migration.py 未创建它，
--      会导致每日刷新静默失败、快照数据陈旧）。
-- ============================================================

-- ------------------------------------------------------------
-- 1. 物化视图唯一索引（必须先有，REFRESH ... CONCURRENTLY 才能工作）
--    MV 仅约 1500~2500 行，非并发创建锁表时间可忽略。
-- ------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshot_code
    ON fund_snapshot (code);

-- ------------------------------------------------------------
-- 2. 列表排序支持索引
--    默认列表 `ORDER BY amount DESC LIMIT n` 无任何 WHERE 时，
--    PG 可直接走索引扫描取 Top-N，省去全 MV 顺序扫描 + 排序。
--   这些列在 migration.py 的 MV 定义中必然存在。
-- ------------------------------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_amount
    ON fund_snapshot (amount DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_premium
    ON fund_snapshot (premium_rate DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_change
    ON fund_snapshot (change_pct DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_turnover
    ON fund_snapshot (turnover_rate DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_volume
    ON fund_snapshot (volume DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_close
    ON fund_snapshot (close DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_nav
    ON fund_snapshot (nav DESC NULLS LAST);

-- ------------------------------------------------------------
-- 3. 过滤 + 排序 组合索引（高频组合）
--    ETF/LOF 分类列表 + 按成交额/溢价率排序是默认高频路径。
-- ------------------------------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_type_amount
    ON fund_snapshot (fund_type, amount DESC NULLS LAST);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snap_type_premium
    ON fund_snapshot (fund_type, premium_rate DESC NULLS LAST);

-- ------------------------------------------------------------
-- 4. fund_daily: 支持 nav_date 查询（配合 _batch_nav_date 的
--    DISTINCT ON 改写，避免返回 N×365 行后在 Python 去重）
-- ------------------------------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_daily_code_navdate
    ON fund_daily (code, nav_date) WHERE nav_date IS NOT NULL;

-- ------------------------------------------------------------
-- 5. fund_daily: 支持 MAX(trade_date) 与近期窗口聚合
--    （idx_daily_date(trade_date DESC) 已存在，补充 (trade_date, code)
--     覆盖 "按日期聚合" 类查询）
-- ------------------------------------------------------------
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_daily_date_code
    ON fund_daily (trade_date, code);

-- ------------------------------------------------------------
-- 6. （可选 / 需 superuser）开启慢查询统计
--     自建 PG 需在 postgresql.conf 设 shared_preload_libraries
--     含 pg_stat_statements 并重启；Supabase 默认已开启。
-- ------------------------------------------------------------
-- CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
