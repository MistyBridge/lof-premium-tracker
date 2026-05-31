-- 002 rollback: 移除 suspension_status 字段
-- 执行: py migration.py rollback 002

DROP INDEX IF EXISTS idx_daily_suspension;
ALTER TABLE fund_daily DROP COLUMN IF EXISTS suspension_status;
