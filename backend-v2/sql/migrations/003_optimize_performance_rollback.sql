-- ============================================================
-- 回滚脚本 (003) — 删除 003 新增的索引
-- ⚠️ 同样不要包裹在事务内（DROP INDEX CONCURRENTLY 不能在事务里）。
-- ============================================================

DROP INDEX CONCURRENTLY IF EXISTS idx_snap_nav;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_close;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_volume;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_turnover;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_change;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_premium;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_amount;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_type_amount;
DROP INDEX CONCURRENTLY IF EXISTS idx_snap_type_premium;
DROP INDEX CONCURRENTLY IF EXISTS idx_daily_code_navdate;
DROP INDEX CONCURRENTLY IF EXISTS idx_daily_date_code;

-- 注意: idx_snapshot_code 是 REFRESH MATERIALIZED VIEW CONCURRENTLY
-- 的必需索引。只有在你确认不再使用 CONCURRENTLY 刷新时才删除:
-- DROP INDEX CONCURRENTLY IF EXISTS idx_snapshot_code;
