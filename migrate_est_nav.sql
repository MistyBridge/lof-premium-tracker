-- 估算净值 5分钟切片入库 - 数据库迁移
ALTER TABLE fund_est_nav ADD COLUMN IF NOT EXISTS snapshot_time TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE fund_est_nav DROP CONSTRAINT IF EXISTS fund_est_nav_pkey;
ALTER TABLE fund_est_nav ADD PRIMARY KEY (code, trade_date, snapshot_time);
